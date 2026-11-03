// Reads {documents: [...], nodes: [...]} as JSON on stdin and writes each one out as Markdown.
// documents: answers from POST /write/visual. nodes: documents built by hand, as JSON.
// tests/test_visual_editor.py checks the results with the same parser that renders articles.
const { readFileSync } = require('node:fs');
const { runInThisContext } = require('node:vm');

const load = file => runInThisContext(readFileSync(file, 'utf8'));
load('src/copydesk/static/vendor/prosemirror/editor-kit.min.js');
load('src/copydesk/static/js/visual-editor.js');
const { createState, schema, toMarkdown } = globalThis.QuillSailVisual;

const input = JSON.parse(readFileSync(0, 'utf8'));
const output = {
  documents: (input.documents || []).map(data => {
    const { state, origin } = createState(data);
    return { kept: toMarkdown(state.doc, origin), rewritten: toMarkdown(state.doc, null) };
  }),
  nodes: (input.nodes || []).map(json => toMarkdown(schema.nodeFromJSON(json), null)),
};
process.stdout.write(JSON.stringify(output));
