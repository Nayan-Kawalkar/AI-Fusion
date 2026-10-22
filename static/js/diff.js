/* Inline Monaco diff of the original selection vs the suggested fix. */
window.DiffView = {
  create(container, original, modified, language, startLine = 1) {
    const editor = monaco.editor.createDiffEditor(container, {
      readOnly: true,
      originalEditable: false,
      renderSideBySide: false,
      automaticLayout: true,
      minimap: { enabled: false },
      scrollBeyondLastLine: false,
      renderOverviewRuler: false,
      fontSize: 12,
      fontFamily: "JetBrains Mono, Consolas, monospace",
      lineNumbers: (n) => String(n + startLine - 1),
      theme: "vs-dark",
    });
    const models = {
      original: monaco.editor.createModel(original, language),
      modified: monaco.editor.createModel(modified, language),
    };
    editor.setModel(models);
    return {
      dispose() {
        editor.dispose();
        models.original.dispose();
        models.modified.dispose();
      },
    };
  },
};
