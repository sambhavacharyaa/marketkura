// Markdown toolbar + live preview for every post/comment body on the site.
//
// Every button just inserts or wraps Markdown syntax around the current selection in the
// existing `<textarea name="body">` — the value submitted to the server is still plain Markdown
// text, so nothing about how posts are stored, validated or rendered changes. Without JavaScript
// a member just gets the plain textarea they always had; this is a pure enhancement.
(function () {
  var PREVIEW_URL = document.body.dataset.markdownPreviewUrl;
  var uid = 0;

  // Server-rendered translations for the labels below (English fallbacks here are just that -
  // fallbacks, in case the json_script tag is ever missing) - see base.html's
  // #md-toolbar-labels and context_processors.site().
  var LABELS = (function () {
    var el = document.getElementById('md-toolbar-labels');
    if (!el) return {};
    try { return JSON.parse(el.textContent); } catch (e) { return {}; }
  })();

  var BUTTONS = [
    { cmd: 'bold', icon: 'bold', label: LABELS.bold || 'Bold', key: 'b' },
    { cmd: 'italic', icon: 'italic', label: LABELS.italic || 'Italic', key: 'i' },
    { cmd: 'strike', icon: 'strike', label: LABELS.strike || 'Strikethrough' },
    'sep',
    { cmd: 'heading', icon: 'heading', label: LABELS.heading || 'Heading' },
    { cmd: 'quote', icon: 'quote', label: LABELS.quote || 'Quote' },
    { cmd: 'code', icon: 'code', label: LABELS.code || 'Code' },
    'sep',
    { cmd: 'bullet', icon: 'list-bullet', label: LABELS.bullet || 'Bulleted list' },
    { cmd: 'numbered', icon: 'list-numbered', label: LABELS.numbered || 'Numbered list' },
    { cmd: 'link', icon: 'link', label: LABELS.link || 'Link', key: 'k' },
  ];
  var SHORTCUTS = { b: 'bold', i: 'italic', k: 'link' };

  var iconMarkup = function (name) {
    return '<svg class="icon" aria-hidden="true"><use href="#i-' + name + '"/></svg>';
  };

  // --- Markdown insertion, operating purely on the textarea's own selection -------------------

  var wrap = function (textarea, before, after, placeholder) {
    var start = textarea.selectionStart, end = textarea.selectionEnd;
    var selected = textarea.value.slice(start, end);
    textarea.setRangeText(before + (selected || placeholder) + after, start, end, 'select');
    if (!selected) {
      // Nothing was selected: select just the placeholder so typing replaces it, not the markers.
      textarea.setSelectionRange(start + before.length, start + before.length + placeholder.length);
    }
    textarea.focus();
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
  };

  // Prefixes every line touched by the current selection (or just the current line, if nothing
  // is selected) — e.g. selecting three lines and clicking "Bulleted list" turns all three into
  // list items in one go.
  var prefixLines = function (textarea, makePrefix) {
    var start = textarea.selectionStart, end = textarea.selectionEnd;
    var value = textarea.value;
    var lineStart = value.lastIndexOf('\n', start - 1) + 1;
    var lineEnd = value.indexOf('\n', end);
    if (lineEnd === -1) lineEnd = value.length;
    var out = value.slice(lineStart, lineEnd).split('\n').map(function (line, i) { return makePrefix(i) + line; }).join('\n');
    textarea.setRangeText(out, lineStart, lineEnd, 'end');
    textarea.focus();
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
  };

  var runCommand = function (textarea, cmd) {
    if (cmd === 'bold') return wrap(textarea, '**', '**', 'bold text');
    if (cmd === 'italic') return wrap(textarea, '_', '_', 'italic text');
    if (cmd === 'strike') return wrap(textarea, '<del>', '</del>', 'strikethrough text');
    if (cmd === 'heading') return prefixLines(textarea, function () { return '### '; });
    if (cmd === 'quote') return prefixLines(textarea, function () { return '> '; });
    if (cmd === 'bullet') return prefixLines(textarea, function () { return '- '; });
    if (cmd === 'numbered') return prefixLines(textarea, function (i) { return (i + 1) + '. '; });
    if (cmd === 'code') {
      var selected = textarea.value.slice(textarea.selectionStart, textarea.selectionEnd);
      return /\n/.test(selected) ? wrap(textarea, '```\n', '\n```', 'code') : wrap(textarea, '`', '`', 'code');
    }
    if (cmd === 'link') {
      var url = window.prompt('Link URL');
      if (!url) return;
      return wrap(textarea, '[', '](' + url.trim() + ')', 'link text');
    }
  };

  // --- Preview tab: rendered server-side, through the exact pipeline a published post uses -----

  var fetchPreview = function (textarea, pane) {
    var form = textarea.closest('form');
    var csrf = form && form.querySelector('input[name="csrfmiddlewaretoken"]');
    if (!PREVIEW_URL || !csrf) { pane.innerHTML = ''; return; }
    pane.setAttribute('aria-busy', 'true');
    fetch(PREVIEW_URL, {
      method: 'POST',
      headers: { 'X-CSRFToken': csrf.value, 'Content-Type': 'application/x-www-form-urlencoded' },
      body: 'body=' + encodeURIComponent(textarea.value),
    }).then(function (response) {
      if (!response.ok) throw new Error('preview request failed');
      return response.text();
    }).then(function (html) {
      pane.innerHTML = html;
    }).catch(function () {
      pane.innerHTML = '<p class="field-errors">Preview failed. Please try again.</p>';
    }).finally(function () {
      pane.removeAttribute('aria-busy');
    });
  };

  // --- Wiring a single textarea ----------------------------------------------------------------

  var enhance = function (textarea) {
    if (textarea.closest('.md-editor')) return; // already enhanced
    uid += 1;
    if (!textarea.id) textarea.id = 'md-body-' + uid;
    var paneId = 'md-preview-' + uid;

    var editor = document.createElement('div');
    editor.className = 'md-editor';

    var toolbarRow = document.createElement('div');
    toolbarRow.className = 'md-toolbar';

    var buttonGroup = document.createElement('div');
    buttonGroup.className = 'md-buttons';
    buttonGroup.setAttribute('role', 'group');
    buttonGroup.setAttribute('aria-label', 'Formatting');
    BUTTONS.forEach(function (b) {
      if (b === 'sep') {
        var sep = document.createElement('span');
        sep.className = 'md-sep';
        sep.setAttribute('aria-hidden', 'true');
        buttonGroup.appendChild(sep);
        return;
      }
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'md-btn';
      btn.title = b.label + (b.key ? ' (Ctrl+' + b.key.toUpperCase() + ')' : '');
      btn.setAttribute('aria-label', b.label);
      btn.innerHTML = iconMarkup(b.icon);
      btn.addEventListener('click', function () { runCommand(textarea, b.cmd); });
      buttonGroup.appendChild(btn);
    });

    var tabs = document.createElement('div');
    tabs.className = 'md-tabs';
    tabs.setAttribute('role', 'tablist');
    var writeTab = document.createElement('button');
    writeTab.type = 'button'; writeTab.className = 'md-tab active'; writeTab.textContent = LABELS.write || 'Write';
    writeTab.setAttribute('role', 'tab'); writeTab.setAttribute('aria-selected', 'true'); writeTab.setAttribute('aria-controls', textarea.id);
    var previewTab = document.createElement('button');
    previewTab.type = 'button'; previewTab.className = 'md-tab'; previewTab.textContent = LABELS.preview || 'Preview';
    previewTab.setAttribute('role', 'tab'); previewTab.setAttribute('aria-selected', 'false'); previewTab.setAttribute('aria-controls', paneId);
    tabs.appendChild(writeTab);
    tabs.appendChild(previewTab);

    toolbarRow.appendChild(buttonGroup);
    toolbarRow.appendChild(tabs);

    var pane = document.createElement('div');
    pane.className = 'md-preview prose';
    pane.id = paneId;
    pane.setAttribute('role', 'tabpanel');
    pane.hidden = true;

    textarea.parentNode.insertBefore(editor, textarea);
    editor.appendChild(toolbarRow);
    editor.appendChild(textarea);
    editor.appendChild(pane);

    var showWrite = function () {
      previewTab.classList.remove('active'); previewTab.setAttribute('aria-selected', 'false');
      writeTab.classList.add('active'); writeTab.setAttribute('aria-selected', 'true');
      textarea.hidden = false; buttonGroup.hidden = false; pane.hidden = true;
      textarea.focus();
    };
    var showPreview = function () {
      writeTab.classList.remove('active'); writeTab.setAttribute('aria-selected', 'false');
      previewTab.classList.add('active'); previewTab.setAttribute('aria-selected', 'true');
      textarea.hidden = true; buttonGroup.hidden = true; pane.hidden = false;
      fetchPreview(textarea, pane);
    };
    writeTab.addEventListener('click', showWrite);
    previewTab.addEventListener('click', showPreview);

    textarea.addEventListener('keydown', function (event) {
      if (!(event.metaKey || event.ctrlKey)) return;
      var cmd = SHORTCUTS[event.key.toLowerCase()];
      if (!cmd) return;
      event.preventDefault();
      runCommand(textarea, cmd);
    });
  };

  var enhanceAll = function () { document.querySelectorAll('textarea[name="body"]').forEach(enhance); };
  enhanceAll();
  // A category/feed swap (see app.js) can bring in a fresh composer textarea that hasn't been
  // enhanced yet; `enhance` itself is a no-op for ones that already have.
  document.body.addEventListener('htmx:afterSettle', enhanceAll);
})();
