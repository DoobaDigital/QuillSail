// The visual editor's commands, run against its real schema without a browser.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { runInThisContext } = require('node:vm');

runInThisContext(readFileSync('src/copydesk/static/vendor/prosemirror/editor-kit.min.js', 'utf8'));
runInThisContext(readFileSync('src/copydesk/static/js/visual-editor.js', 'utf8'));
const V = globalThis.QuillSailVisual;
const { TextSelection, NodeSelection } = globalThis.QuillSailEditorKit.state;

const paragraph = text => ({ type: 'paragraph', content: text ? [{ type: 'text', text }] : undefined });
const block = (node, source, gap = '\n\n') => ({ node, source, gap });

function open(blocks, trailing = '') {
  const { state, origin } = V.createState({ blocks, trailing });
  return { state, origin };
}

function run(editor, command) {
  let changed = false;
  const ran = command(editor.state, tr => { editor.state = editor.state.apply(tr); changed = true; });
  return ran && changed;
}

const select = (editor, from, to = from) => {
  editor.state = editor.state.apply(editor.state.tr.setSelection(TextSelection.create(editor.state.doc, from, to)));
};
const md = editor => V.toMarkdown(editor.state.doc, editor.origin);
const type = (editor, text) => { editor.state = editor.state.apply(editor.state.tr.insertText(text)); };

test('an empty document writes nothing', () => {
  const editor = open([]);
  assert.equal(md(editor), '');
});

test('marks, headings and quotes toggle on and off', () => {
  const editor = open([block(paragraph('word'), 'word', '')]);
  select(editor, 1, 5);
  run(editor, V.commands.bold());
  assert.equal(md(editor), '**word**');
  assert.equal(V.describe(editor.state).bold, true);
  run(editor, V.commands.bold());
  assert.equal(md(editor), 'word');
  run(editor, V.commands.heading(3));
  assert.equal(md(editor), '### word');
  assert.equal(V.describe(editor.state).heading, 3);
  run(editor, V.commands.heading(3));
  assert.equal(md(editor), 'word');
  run(editor, V.commands.quote());
  assert.equal(md(editor), '> word');
  run(editor, V.commands.quote());
  assert.equal(md(editor), 'word');
});

test('lists switch type and task lists tick', () => {
  const editor = open([block(paragraph('item'), 'item', '')]);
  select(editor, 2);
  run(editor, V.commands.ul());
  assert.equal(md(editor), '- item');
  run(editor, V.commands.ol());
  assert.equal(md(editor), '1. item');
  run(editor, V.commands.ul());
  run(editor, V.commands.task());
  assert.equal(md(editor), '- [ ] item');
  run(editor, V.commands.check());
  assert.equal(md(editor), '- [x] item');
  run(editor, V.commands.task());
  assert.equal(md(editor), '- item');
  run(editor, V.commands.ul());
  assert.equal(md(editor), 'item');
  run(editor, V.commands.task());
  assert.equal(md(editor), '- [ ] item');
});

test('a code block keeps its language and text', () => {
  const editor = open([block(paragraph('x = 1'), 'x = 1', '')]);
  select(editor, 2);
  run(editor, V.commands.codeblock());
  run(editor, V.commands.language('python'));
  assert.equal(md(editor), '```python\nx = 1\n```');
  assert.equal(V.describe(editor.state).language, 'python');
});

test('callouts change kind and title', () => {
  const editor = open([block(paragraph('Boxed'), 'Boxed', '')]);
  select(editor, 2);
  run(editor, V.commands.callout());
  assert.equal(md(editor), '::: tip\nBoxed\n:::');
  run(editor, V.commands.calloutSet({ kind: 'warning', title: 'Careful' }));
  assert.equal(md(editor), '::: warning Careful\nBoxed\n:::');
  run(editor, V.commands.callout());
  assert.equal(md(editor), 'Boxed');
});

test('links are added, changed and removed whole, and unsafe ones are refused', () => {
  const editor = open([block(paragraph('some words'), 'some words', '')]);
  select(editor, 1, 5);
  assert.equal(V.commands.link({ href: 'javascript:alert(1)' })(editor.state, () => assert.fail('dispatched')), false);
  run(editor, V.commands.link({ href: 'https://a.example' }));
  assert.equal(md(editor), '[some](https://a.example) words');
  select(editor, 3);
  assert.equal(V.describe(editor.state).linkHref, 'https://a.example');
  assert.equal(V.describe(editor.state).linkText, 'some');
  run(editor, V.commands.link({ href: 'https://b.example' }, 'other'));
  assert.equal(md(editor), '[other](https://b.example) words');
  select(editor, 3);
  run(editor, V.commands.unlink());
  assert.equal(md(editor), 'other words');
});

test('a link with its own address as text is written as the address', () => {
  const editor = open([block(paragraph(''), '', '')]);
  select(editor, 1);
  run(editor, V.commands.link({ href: 'https://a.example/x' }));
  assert.equal(md(editor), '<https://a.example/x>');
});

test('unsafe addresses are never accepted', () => {
  for (const bad of ['javascript:alert(1)', 'JAVASCRIPT:alert(1)', ' java\nscript:alert(1)', 'data:text/html,x', 'vbscript:x', 'file:///etc/passwd']) {
    assert.equal(V.safeUrl(bad), false, bad);
  }
  for (const good of ['https://a.example', 'http://a.example', 'mailto:a@b.example', '/path', '#section', 'relative/path']) {
    assert.equal(V.safeUrl(good), true, good);
  }
  assert.equal(V.safeUrl('mailto:a@b.example', true), false);
  assert.equal(V.safeUrl('data:image/png;base64,AAAA', true), false);
});

test('images keep their description', () => {
  const editor = open([block(paragraph(''), '', '')]);
  select(editor, 1);
  run(editor, V.commands.image({ src: '/uploads/a.png', alt: 'First' }));
  assert.equal(md(editor), '![First](/uploads/a.png)');
  editor.state = editor.state.apply(editor.state.tr.setSelection(NodeSelection.create(editor.state.doc, 1)));
  assert.deepEqual(V.describe(editor.state).image, { alt: 'First', src: '/uploads/a.png' });
  run(editor, V.commands.imageAlt('A [better] one'));
  assert.equal(md(editor), '![A \\[better\\] one](/uploads/a.png)');
  assert.equal(V.commands.image({ src: 'javascript:alert(1)' })(editor.state, () => assert.fail('dispatched')), false);
});

test('footnotes get the next free number and their text goes to the end', () => {
  const editor = open([block(paragraph('Text'), 'Text', '')]);
  select(editor, 5);
  run(editor, V.commands.footnote('First'));
  select(editor, 1);
  run(editor, V.commands.footnote('Second'));
  assert.equal(md(editor), '[^2]Text[^1]\n\n[^1]: First\n\n[^2]: Second');
});

test('footnote numbers skip ones used in kept source', () => {
  const raw = { type: 'raw_block', content: [{ type: 'text', text: 'Old[^1] ^[inline]' }] };
  const editor = open([block(paragraph('Text'), 'Text', ''), block(raw, 'Old[^1] ^[inline]')]);
  select(editor, 5);
  run(editor, V.commands.footnote('New'));
  assert.match(md(editor), /Text\[\^2\]/);
  assert.match(md(editor), /Old\[\^1\] \^\[inline\]/);
});

test('tables can grow and shrink, and pipes stay inside cells', () => {
  const editor = open([block(paragraph(''), '', '')]);
  select(editor, 1);
  run(editor, V.commands.table());
  assert.equal(V.describe(editor.state).table, true);
  type(editor, 'a|b');
  assert.equal(md(editor), '| a\\|b |  |\n| --- | --- |\n|  |  |');
  run(editor, V.commands.addRowAfter());
  assert.equal(md(editor).split('\n').length, 4);
  run(editor, V.commands.addColumnAfter());
  assert.equal(md(editor).split('\n')[1], '| --- | --- | --- |');
  run(editor, V.commands.deleteColumn());
  assert.equal(md(editor).split('\n')[1], '| --- | --- |');
  run(editor, V.commands.deleteTable());
  assert.equal(md(editor).trim(), '');
});

test('nothing changes for blocks nobody touched, and undo restores the original text', () => {
  const blocks = [
    block({ type: 'heading', attrs: { level: 1 }, content: [{ type: 'text', text: 'Title' }] }, 'Title\n=====', '\n'),
    block(paragraph('Soft break here'), 'Soft break\nhere', '\n\n\n'),
    block({ type: 'bullet_list', attrs: { bullet: '*', tight: true }, content: [
      { type: 'list_item', content: [paragraph('one')] },
    ] }, '* one'),
  ];
  const editor = open(blocks, '\n');
  const original = md(editor);
  assert.equal(original, '\nTitle\n=====\n\n\nSoft break\nhere\n\n* one\n');
  const before = editor.state;
  select(editor, 9);
  type(editor, 'X');
  assert.match(md(editor), /^\nTitle\n=====\n\nSXoft break here\n\n\* one\n$/);
  run(editor, V.commands.undo());
  assert.equal(editor.state.doc.eq(before.doc), true);
  assert.equal(md(editor), original);
});

test('moving a block keeps its original text', () => {
  const one = block(paragraph('one'), 'one  ', '');
  const two = block(paragraph('two'), 'two', '\n\n');
  const editor = open([one, two]);
  const { doc } = editor.state;
  const first = doc.child(0);
  const tr = editor.state.tr.delete(0, first.nodeSize).insert(doc.child(1).nodeSize, first);
  editor.state = editor.state.apply(tr);
  assert.equal(md(editor), 'two\n\none  ');
});

test('a server block the schema rejects stays as source', () => {
  const editor = open([block({ type: 'list_item', content: [] }, 'odd text', '')]);
  assert.equal(editor.state.doc.firstChild.type.name, 'raw_block');
  assert.equal(md(editor), 'odd text');
});

test('a table, code block or rule at the end leaves a line below it', () => {
  const editor = open([block(paragraph(''), '', '')]);
  select(editor, 1);
  run(editor, V.commands.codeblock());
  assert.equal(editor.state.doc.lastChild.type.name, 'paragraph');
  assert.equal(md(editor), '```\n\n```');
});

test('two lists in a row stay two lists', () => {
  const list = text => ({ type: 'bullet_list', attrs: { bullet: '-', tight: true }, content: [{ type: 'list_item', content: [paragraph(text)] }] });
  const { doc } = open([block(list('a'), '- a', ''), block(list('b'), '- b')]).state;
  assert.equal(V.toMarkdown(doc, null), '- a\n\n* b');
});
