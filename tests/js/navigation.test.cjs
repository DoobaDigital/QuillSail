// Menu buttons on narrow screens (issue #34), run against app.js with a small fake DOM.
// tests/test_mobile_menus.py checks that the real templates have the same structure.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { runInNewContext } = require('node:vm');
const code = readFileSync('src/copydesk/static/js/app.js', 'utf8');

class Node {
  constructor(tag, attrs = {}, children = []) {
    this.tagName = tag.toUpperCase();
    this.attrs = { ...attrs };
    this.classes = new Set((attrs.class || '').split(/\s+/).filter(Boolean));
    delete this.attrs.class;
    this.children = [];
    this.parent = null;
    this.listeners = {};
    this.hidden = false;
    const classes = this.classes;
    this.classList = {
      contains: name => classes.has(name),
      add: name => classes.add(name),
      remove: name => classes.delete(name),
      toggle: (name, force) => {
        const on = force === undefined ? !classes.has(name) : force;
        if (on) classes.add(name); else classes.delete(name);
        return on;
      },
    };
    children.forEach(child => this.append(child));
  }
  append(child) { child.parent = this; this.children.push(child); return child; }
  get id() { return this.attrs.id || ''; }
  getAttribute(name) { return name in this.attrs ? this.attrs[name] : null; }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  hasAttribute(name) { return name in this.attrs; }
  removeAttribute(name) { delete this.attrs[name]; }
  addEventListener(type, listener) { (this.listeners[type] ||= []).push(listener); }
  dispatch(type, event = {}) {
    event.type = type;
    event.target = event.target || this;
    event.preventDefault = () => {};
    for (let node = this; node; node = node.parent) (node.listeners[type] || []).forEach(fn => fn(event));
    return event;
  }
  click() { return this.dispatch('click'); }
  focus() { root.activeElement = this; this.dispatch('focusin'); }
  contains(other) { for (let node = other; node; node = node.parent) if (node === this) return true; return false; }
  closest(selector) { for (let node = this; node && node.tagName !== '#DOCUMENT'; node = node.parent) if (matches(node, selector)) return node; return null; }
  descendants() { return this.children.flatMap(child => [child, ...child.descendants()]); }
  querySelectorAll(selector) { return this.descendants().filter(node => matches(node, selector)); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}

// Enough CSS selector support for app.js: tags, classes, attributes, commas and descendants.
function matchesCompound(node, compound) {
  const parts = compound.match(/^([a-z]+)?((?:\.[\w-]+|\[[^\]]+\])*)$/i);
  if (!parts) throw new Error('Unsupported selector: ' + compound);
  if (parts[1] && node.tagName !== parts[1].toUpperCase()) return false;
  for (const piece of parts[2].match(/\.[\w-]+|\[[^\]]+\]/g) || []) {
    if (piece[0] === '.') { if (!node.classes.has(piece.slice(1))) return false; continue; }
    const [name, value] = piece.slice(1, -1).split('=');
    if (!(name in node.attrs)) return false;
    if (value !== undefined && node.attrs[name] !== value.replace(/"/g, '')) return false;
  }
  return true;
}

function matches(node, selector) {
  return selector.split(',').some(group => {
    const steps = group.trim().split(/\s+/);
    if (!matchesCompound(node, steps.pop())) return false;
    let ancestor = node.parent;
    for (const step of steps.reverse()) {
      while (ancestor && !matchesCompound(ancestor, step)) ancestor = ancestor.parent;
      if (!ancestor) return false;
      ancestor = ancestor.parent;
    }
    return true;
  });
}

const el = (tag, attrs, children) => new Node(tag, attrs, children);
let root;

function load(body) {
  root = el('#document');
  const html = root.append(el('html', { class: 'no-js', 'data-default-theme': 'light' }));
  html.append(el('body', {}, body));
  root.documentElement = html;
  root.activeElement = null;
  root.getElementById = id => root.querySelector('[id=' + id + ']');
  const storage = new Map();
  runInNewContext(code, {
    document: root,
    window: { addEventListener() {}, confirm: () => true },
    localStorage: { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) },
    navigator: {},
    setTimeout,
  });
  return root;
}

const escape = () => root.dispatch('keydown', { key: 'Escape', target: root.activeElement || root });

function publicationPage() {
  const link = el('a', { href: '/issues/' });
  const menu = el('nav', { class: 'site-nav', 'aria-label': 'Main' }, [
    el('ul', { class: 'nav-list', id: 'cd-nav-menu' }, [el('li', {}, [link])]),
  ]);
  const button = el('button', { class: 'button nav-toggle', type: 'button', 'data-nav-toggle': '', 'aria-expanded': 'false', 'aria-controls': 'cd-nav-menu' });
  const header = el('div', { class: 'container header-inner', 'data-nav': '' }, [el('a', { class: 'brand', href: '/' }), button, menu]);
  load([el('header', { class: 'site-header' }, [header]), el('main', { id: 'cd-main' })]);
  return { button, menu, header, link };
}

function dashboardPage() {
  const close = el('button', { class: 'button dash-nav-close', type: 'button', 'data-dash-nav-close': '' });
  const navLink = el('a', { href: '/dashboard/articles' });
  const sidebar = el('aside', { class: 'dash-sidebar', id: 'cd-dash-nav' }, [close, el('a', { class: 'dash-brand', href: '/dashboard/' }), navLink]);
  const scrim = el('div', { class: 'dash-scrim', 'aria-hidden': 'true' });
  const toggle = el('button', { class: 'button nav-button', type: 'button', 'data-dash-nav-toggle': '', 'aria-controls': 'cd-dash-nav', 'aria-expanded': 'false' });
  const content = el('a', { href: '/dashboard/issues' });
  const dash = el('div', { class: 'dash' }, [sidebar, scrim, el('div', { class: 'dash-main' }, [el('div', { class: 'dash-topbar' }, [toggle]), el('main', {}, [content])])]);
  load([dash]);
  return { dash, sidebar, close, scrim, toggle, navLink, content };
}

test('publication Menu shows the links on .site-nav and hides them again', () => {
  const page = publicationPage();
  page.button.click();
  assert.equal(page.menu.classList.contains('is-open'), true);
  assert.equal(page.button.getAttribute('aria-expanded'), 'true');
  page.button.click();
  assert.equal(page.menu.classList.contains('is-open'), false);
  assert.equal(page.button.getAttribute('aria-expanded'), 'false');
});

test('Escape closes the publication menu and returns focus to Menu', () => {
  const page = publicationPage();
  page.button.click();
  page.link.focus();
  escape();
  assert.equal(page.menu.classList.contains('is-open'), false);
  assert.equal(page.button.getAttribute('aria-expanded'), 'false');
  assert.equal(root.activeElement, page.button);
});

test('dashboard Menu opens the drawer and moves focus to its Close button', () => {
  const page = dashboardPage();
  page.toggle.click();
  assert.equal(page.dash.classList.contains('nav-open'), true);
  assert.equal(page.toggle.getAttribute('aria-expanded'), 'true');
  assert.equal(root.activeElement, page.close);
  page.navLink.focus();
  assert.equal(page.dash.classList.contains('nav-open'), true, 'moving within the drawer keeps it open');
});

for (const [name, close] of [
  ['Close button', page => page.close.click()],
  ['dimmed area', page => page.scrim.click()],
  ['Escape', () => escape()],
  ['Menu button again', page => page.toggle.click()],
]) {
  test(`dashboard drawer closes with the ${name}, resets aria-expanded and returns focus`, () => {
    const page = dashboardPage();
    page.toggle.click();
    close(page);
    assert.equal(page.dash.classList.contains('nav-open'), false);
    assert.equal(page.toggle.getAttribute('aria-expanded'), 'false');
    assert.equal(root.activeElement, page.toggle);
  });
}

test('tabbing out of the dashboard drawer closes it without stealing focus', () => {
  const page = dashboardPage();
  page.toggle.click();
  page.content.focus();
  assert.equal(page.dash.classList.contains('nav-open'), false);
  assert.equal(page.toggle.getAttribute('aria-expanded'), 'false');
  assert.equal(root.activeElement, page.content);
});

test('other keys leave both menus as they are', () => {
  const page = dashboardPage();
  page.toggle.click();
  root.dispatch('keydown', { key: 'Enter' });
  assert.equal(page.dash.classList.contains('nav-open'), true);
});
