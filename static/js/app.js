// Small progressive enhancements. Every feature also works without JavaScript.
(function () {
  // Show thesis / AMA fields only for the matching post type.
  var type = document.getElementById('id_type');
  if (type) {
    var toggle = function () {
      document.querySelectorAll('[data-show-for]').forEach(function (el) {
        el.hidden = el.getAttribute('data-show-for').split(' ').indexOf(type.value) === -1;
      });
    };
    type.addEventListener('change', toggle);
    toggle();
  }

  // Quick composer's image attach button is a <label for> a visually-hidden file input (so the
  // native picker still opens with no JS at all) — this just reflects the chosen filename back
  // into the label so picking a file doesn't look like nothing happened.
  var composerImage = document.getElementById('c-image');
  if (composerImage) {
    composerImage.addEventListener('change', function () {
      var nameEl = document.querySelector('.composer-image-name');
      var label = composerImage.closest('.composer-image-label');
      if (!nameEl) return;
      if (composerImage.files && composerImage.files[0]) {
        nameEl.textContent = composerImage.files[0].name;
        if (label) label.classList.add('has-file');
      } else {
        nameEl.textContent = nameEl.dataset.default || nameEl.textContent;
        if (label) label.classList.remove('has-file');
      }
    });
  }

  // "/" or Ctrl/Cmd+K focuses the header search, unless the user is already typing somewhere.
  var search = document.getElementById('site-search');
  if (search) {
    document.addEventListener('keydown', function (event) {
      var target = event.target, typing = target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName));
      var wantsSearch = (event.key === '/' && !typing && !event.metaKey && !event.ctrlKey) || ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k');
      if (wantsSearch) { event.preventDefault(); search.focus(); search.select(); }
    });
  }

  // Market hours: open/closed from each exchange's regular weekday sessions, in its own time zone.
  // This is a schedule, not live data, so exchange holidays are not reflected. Re-run after every
  // htmx swap of #main (see the feed/category navigation below): that can replace the rail with a
  // brand-new `.hours` element that has no listener bound to it yet.
  var DAY = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
  var toMinutes = function (hhmm) { var p = hhmm.split(':'); return parseInt(p[0], 10) * 60 + parseInt(p[1], 10); };
  var hoursTimer = null;
  var setupHours = function () {
    var list = document.querySelector('.hours');
    if (hoursTimer) { clearInterval(hoursTimer); hoursTimer = null; }
    if (!list || !window.Intl || !Intl.DateTimeFormat) return;
    var render = function () {
      list.querySelectorAll('li[data-tz]').forEach(function (row) {
        try {
          var parts = {};
          new Intl.DateTimeFormat('en-GB', { timeZone: row.dataset.tz, weekday: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
            .formatToParts(new Date()).forEach(function (p) { parts[p.type] = p.value; });
          var now = parseInt(parts.hour, 10) * 60 + parseInt(parts.minute, 10);
          var tradingDay = row.dataset.days.split(',').indexOf(String(DAY[parts.weekday])) !== -1;
          var open = tradingDay && row.dataset.sessions.split(',').some(function (s) {
            var r = s.split('-'); return now >= toMinutes(r[0]) && now < toMinutes(r[1]);
          });
          row.classList.toggle('is-open', open);
          row.querySelector('.hours-time').textContent = parts.hour + ':' + parts.minute;
          row.querySelector('.hours-status').textContent = open ? list.dataset.open : list.dataset.closed;
        } catch (e) { /* unknown time zone: leave the row blank */ }
      });
    };
    render();
    hoursTimer = setInterval(render, 60000);
  };
  setupHours();
  document.body.addEventListener('htmx:afterSettle', setupHours);

  // Sticky header gains a deeper shadow once the page has scrolled, for a sense of depth.
  var header = document.querySelector('.site-header');
  if (header) {
    var setScrolled = function () { header.classList.toggle('scrolled', window.scrollY > 4); };
    setScrolled();
    document.addEventListener('scroll', setScrolled, { passive: true });
  }

  // Notification / user menus: close on outside click or Escape, with a scrim behind them, and
  // return focus to the button that opened them (standard menu/disclosure behaviour).
  var openMenus = function () { return Array.prototype.slice.call(document.querySelectorAll('.menu[open]')); };
  var scrim = null;
  var getScrim = function () {
    if (!scrim) {
      scrim = document.createElement('div');
      scrim.className = 'menu-scrim';
      scrim.setAttribute('aria-hidden', 'true');
      document.body.appendChild(scrim);
      scrim.addEventListener('click', function () { closeMenus(); });
    }
    return scrim;
  };
  var closeMenus = function (opts) {
    var menus = openMenus();
    menus.forEach(function (menu) {
      menu.removeAttribute('open');
      if (opts && opts.returnFocus) {
        var summary = menu.querySelector('summary');
        if (summary) summary.focus();
      }
    });
    if (scrim) scrim.classList.remove('show');
  };
  document.addEventListener('toggle', function (event) {
    var menu = event.target;
    if (!(menu instanceof HTMLElement) || !menu.matches('.menu')) return;
    if (menu.open) {
      openMenus().forEach(function (other) { if (other !== menu) other.removeAttribute('open'); });
      // .menu-no-scrim opts a small, local menu (e.g. the post share dropdown) out of the
      // page-wide dimming backdrop — that treatment belongs to the account-level menus
      // (notifications/user/language) it was designed for, not a lightweight inline action.
      if (!menu.matches('.menu-no-scrim')) getScrim().classList.add('show');
    } else if (!openMenus().length && scrim) {
      scrim.classList.remove('show');
    }
  }, true);
  document.addEventListener('click', function (event) {
    openMenus().forEach(function (menu) { if (!menu.contains(event.target)) menu.removeAttribute('open'); });
    if (!openMenus().length && scrim) scrim.classList.remove('show');
  });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && openMenus().length) closeMenus({ returnFocus: true });
  });

  // Off-canvas sidebar (mobile/tablet only — on wide screens it's always visible in the layout).
  // Two separate buttons can open it on narrow phones: the header hamburger and the bottom
  // navigation bar's "Menu" item, so this tracks all `.sidebar-toggle` elements rather than one id.
  if (document.getElementById('site-sidebar') && document.querySelector('.sidebar-toggle')) {
    // #site-sidebar, #sidebar-scrim and every .sidebar-toggle button all live inside #app-shell,
    // which every htmx navigation replaces wholesale (outerHTML, not patched in place). Caching
    // any of them once here would silently start operating on a detached node after the first
    // swap — exactly the "hamburger sometimes does nothing" bug this fixes. Looking each one up
    // fresh inside every handler, and delegating clicks on `document` rather than binding
    // listeners directly to elements that get replaced, sidesteps the staleness entirely.
    var getSidebar = function () { return document.getElementById('site-sidebar'); };
    var getScrim = function () { return document.getElementById('sidebar-scrim'); };
    var getToggles = function () { return Array.prototype.slice.call(document.querySelectorAll('.sidebar-toggle')); };
    var openSidebar = function () {
      getSidebar().classList.add('is-open');
      getScrim().hidden = false;
      getToggles().forEach(function (btn) { btn.setAttribute('aria-expanded', 'true'); });
      document.body.classList.add('sidebar-lock');
      var closeBtn = document.getElementById('sidebar-close');
      if (closeBtn) closeBtn.focus();
    };
    var closeSidebar = function (opts) {
      getSidebar().classList.remove('is-open');
      getScrim().hidden = true;
      getToggles().forEach(function (btn) { btn.setAttribute('aria-expanded', 'false'); });
      document.body.classList.remove('sidebar-lock');
      if (opts && opts.returnFocus) { var toggles = getToggles(); if (toggles[0]) toggles[0].focus(); }
    };
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && getSidebar().classList.contains('is-open')) closeSidebar({ returnFocus: true });
    });
    window.addEventListener('pageshow', function () { closeSidebar(); });
    // Covers the hamburger toggles, the scrim, the close button, and sidebar links that fetch
    // their destination via htmx (see the feed/category swap below) and so stay on the same
    // document — all delegated through one listener so none of it depends on a specific element
    // still being attached by the time it's clicked.
    document.body.addEventListener('click', function (event) {
      if (event.target.closest('.sidebar-toggle')) { openSidebar(); return; }
      if (event.target.closest('#sidebar-close')) { closeSidebar({ returnFocus: true }); return; }
      if (event.target.closest('#sidebar-scrim')) { closeSidebar(); return; }
      if (getSidebar().contains(event.target) && event.target.closest('a')) closeSidebar();
    });
    // Resizing past the off-canvas breakpoint while open should still reset state so it doesn't
    // linger "open".
    window.addEventListener('resize', function () {
      if (window.innerWidth > 1099 && getSidebar().classList.contains('is-open')) closeSidebar();
    });
  }

  // Top progress bar: a lightweight sense of "something is happening" for full page navigations
  // and htmx requests. Purely cosmetic — it never blocks or delays the underlying action.
  var bar = document.createElement('div');
  bar.id = 'nav-progress';
  bar.setAttribute('aria-hidden', 'true');
  document.body.insertBefore(bar, document.body.firstChild);
  var barTimer = null;
  var startBar = function () {
    clearTimeout(barTimer);
    bar.classList.add('is-active');
    bar.style.width = '0';
    // Force a reflow so the width transition from 0 is picked up before jumping to ~75%.
    void bar.offsetWidth;
    bar.style.width = '78%';
  };
  var finishBar = function () {
    bar.style.width = '100%';
    barTimer = setTimeout(function () { bar.classList.remove('is-active'); bar.style.width = '0'; }, 250);
  };
  document.body.addEventListener('htmx:beforeRequest', startBar);
  document.body.addEventListener('htmx:afterRequest', finishBar);
  document.addEventListener('click', function (event) {
    var link = event.target.closest && event.target.closest('a[href]');
    if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if (link.target === '_blank' || link.hasAttribute('download') || link.hasAttribute('hx-get') || link.hasAttribute('hx-post')) return;
    var url; try { url = new URL(link.href, window.location.href); } catch (e) { return; }
    if (url.origin !== window.location.origin) return;
    if (url.pathname === window.location.pathname && url.search === window.location.search && url.hash) return; // same-page anchor
    startBar();
  });
  document.addEventListener('submit', function (event) {
    var form = event.target;
    if (form instanceof HTMLFormElement && !form.hasAttribute('hx-post') && !form.hasAttribute('hx-get')) startBar();
  });
  window.addEventListener('pageshow', function () { bar.classList.remove('is-active'); bar.style.width = '0'; });

  // Disable + spin the submit button on ordinary (non-htmx) forms so a click always gets an
  // immediate, visible response and can't be double-submitted while the page reloads.
  document.addEventListener('submit', function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement) || form.hasAttribute('hx-post') || form.hasAttribute('hx-get')) return;
    var button = form.querySelector('button[type="submit"], input[type="submit"]');
    if (button && !button.disabled) { button.classList.add('is-loading'); button.disabled = true; }
  });
  window.addEventListener('pageshow', function (event) {
    if (event.persisted) {
      document.querySelectorAll('.is-loading').forEach(function (el) { el.classList.remove('is-loading'); el.disabled = false; });
    }
  });

  // The "More filters" form is a plain GET form — without this, an unchanged "All"/empty select
  // still submits as e.g. &type= and litters the URL. Disabling a field removes it from the
  // submitted query string; nothing to undo afterwards since the page navigates away anyway.
  document.addEventListener('submit', function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement) || !form.matches('.filter-form')) return;
    Array.prototype.forEach.call(form.elements, function (field) {
      if (field.name && !field.value) field.disabled = true;
    });
  });

  // Briefly highlight a vote control right after the member's own click toggles it (not on
  // every ordinary page load, so an already-voted feed doesn't animate on every visit).
  // The vote forms target their own id (outerHTML swap), so `detail.elt` — the element that
  // made the request — carries the same id as the freshly-swapped-in replacement; look that
  // replacement up by id rather than trusting the (possibly now-detached) event target.
  //
  // This has to wait for "htmx:afterSettle", not "htmx:afterSwap": htmx settles the `class`
  // attribute itself a beat after swapping (`attributesToSettle`, ~20ms later, by design — it's
  // what lets a *server-driven* class change transition smoothly) and that settle overwrites
  // whatever classes got added in between, including ours. Adding it on afterSwap meant the
  // class was wiped before the animation had any real time to play.
  document.body.addEventListener('htmx:afterSettle', function (event) {
    var elt = event.detail && event.detail.elt;
    var id = elt && elt.id;
    if (!id || !/^(card-vote-|post-vote$|comment-vote-)/.test(id)) return;
    var current = document.getElementById(id);
    if (!current) return;
    current.classList.add('just-voted');
    setTimeout(function () { current.classList.remove('just-voted'); }, 450);
  });

  // Thread-list skeleton (see post_list.html): only reveal it if the feed/category request is
  // still running after a short delay. Most requests — including an empty category, which has
  // nothing to query — settle almost immediately, and flashing the skeleton on just to replace it
  // with "No posts match this view yet." a moment later reads as broken rather than loading.
  //
  // The tab/chip-filter links on the home page swap their own ancestor (#feed-results), which
  // removes the clicked <a> from the document as part of settling the response. A *second*
  // listener for "htmx:afterRequest" on document.body would miss that: htmx dispatches the event
  // on the (by then detached) link, and a detached node's events never bubble anywhere. Listening
  // directly on the request's XHR object sidesteps that entirely — it fires regardless of what the
  // swap does to the DOM — and a request id guards against a stale timer from an older, overlapping
  // request clobbering a newer one's state.
  var isSkeletonTrigger = function (elt) { return !!elt && elt.getAttribute && elt.getAttribute('hx-indicator') === '#thread-skeleton'; };
  var skeletonTimer = null;
  var skeletonRequestId = 0;
  document.body.addEventListener('htmx:beforeRequest', function (event) {
    if (!isSkeletonTrigger(event.target)) return;
    clearTimeout(skeletonTimer);
    var requestId = ++skeletonRequestId;
    skeletonTimer = setTimeout(function () {
      if (requestId !== skeletonRequestId) return;
      var skeleton = document.getElementById('thread-skeleton');
      if (skeleton) skeleton.classList.add('is-visible');
    }, 200);
    var xhr = event.detail && event.detail.xhr;
    var hide = function () {
      if (requestId !== skeletonRequestId) return;
      clearTimeout(skeletonTimer);
      var skeleton = document.getElementById('thread-skeleton');
      if (skeleton) skeleton.classList.remove('is-visible');
    };
    if (xhr) { xhr.addEventListener('loadend', hide); } else { document.body.addEventListener('htmx:afterRequest', hide, { once: true }); }
  });

  // "Join the discussion" banner: once dismissed, remembered per browser so it doesn't keep
  // reappearing. Without JavaScript (or if storage is blocked) it just stays visible, which is
  // the safe default for a signup prompt.
  var promoBanner = document.getElementById('promo-banner');
  var promoBannerClose = document.getElementById('promo-banner-close');
  if (promoBanner && promoBannerClose) {
    var DISMISS_KEY = 'mk-promo-banner-dismissed';
    var isDismissed = false;
    try { isDismissed = localStorage.getItem(DISMISS_KEY) === '1'; } catch (e) { /* storage unavailable: show the banner */ }
    if (isDismissed) {
      promoBanner.remove();
    } else {
      promoBannerClose.addEventListener('click', function () {
        promoBanner.remove();
        try { localStorage.setItem(DISMISS_KEY, '1'); } catch (e) { /* ignore: nothing to persist to */ }
      });
    }
  }

  // Post share button: on a device/browser with the native Web Share API, skip our own
  // Copy link/WhatsApp/Facebook dropdown entirely and hand off to the OS's own share sheet
  // instead. preventDefault() on the summary's click stops <details> from opening at all, so the
  // "toggle" listener above (scrim, closing other menus) never even sees this interaction.
  // Browsers without navigator.share (desktop Firefox, old browsers, no JS at all) get the
  // dropdown exactly as before — this is a progressive enhancement, not a replacement.
  document.addEventListener('click', function (event) {
    var summary = event.target.closest && event.target.closest('.share-menu > summary');
    if (!summary || !navigator.share) return;
    event.preventDefault();
    navigator.share({ title: summary.dataset.shareTitle, url: summary.dataset.shareUrl }).catch(function () {
      // AbortError (user dismissed the sheet) or any other failure: nothing to do, same as
      // closing our own dropdown without picking an option.
    });
  });

  // Post share menu's "Copy link" button. Delegated to document (not bound per-button) since the
  // share menu is inside #main and gets replaced wholesale on every htmx navigation.
  document.addEventListener('click', function (event) {
    var button = event.target.closest && event.target.closest('.share-copy');
    if (!button) return;
    event.preventDefault();
    var url = button.getAttribute('data-share-url');
    var label = button.querySelector('span');
    var restore = label ? label.textContent : null;
    var showCopied = function () {
      if (!label) return;
      label.textContent = button.dataset.copiedLabel || restore;
      button.classList.add('copied');
      setTimeout(function () { label.textContent = restore; button.classList.remove('copied'); }, 1500);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(url).then(showCopied, showCopied);
    } else {
      var temp = document.createElement('textarea');
      temp.value = url;
      temp.style.position = 'fixed';
      temp.style.opacity = '0';
      document.body.appendChild(temp);
      temp.select();
      try { document.execCommand('copy'); } catch (e) { /* nothing more we can do */ }
      document.body.removeChild(temp);
      showCopied();
    }
  });

  // Signup/login password show/hide toggle.
  document.addEventListener('click', function (event) {
    var button = event.target.closest && event.target.closest('.password-toggle');
    if (!button) return;
    var input = button.previousElementSibling;
    if (!input) return;
    if (!button.dataset.hiddenLabel) button.dataset.hiddenLabel = button.textContent;
    var shown = input.type === 'text';
    input.type = shown ? 'password' : 'text';
    button.setAttribute('aria-pressed', String(!shown));
    button.textContent = shown ? button.dataset.hiddenLabel : button.dataset.shownLabel;
  });
})();
