/* Platform Defaults: filters, copy and share buttons, optional cookieless counts, and a self-test
   (?selftest=1) that headless Chrome runs in CI against the built and the live site. */
(function () {
  "use strict";
  var errors = [];
  window.addEventListener("error", function (e) { errors.push(String(e.message || e)); });

  function count(name) {
    try { if (window.goatcounter && window.goatcounter.count) window.goatcounter.count({ path: name, event: true }); } catch (e) { /* counting is optional */ }
  }
  function flash(btn, text) {
    var old = btn.textContent;
    btn.textContent = text;
    setTimeout(function () { btn.textContent = old; }, 1600);
  }

  // Filters on the home page: show cards whose training answer matches.
  var filterButtons = document.querySelectorAll("[data-filter]");
  Array.prototype.forEach.call(filterButtons, function (btn) {
    btn.addEventListener("click", function () {
      var want = btn.getAttribute("data-filter");
      Array.prototype.forEach.call(filterButtons, function (b) { b.setAttribute("aria-pressed", b === btn ? "true" : "false"); });
      Array.prototype.forEach.call(document.querySelectorAll(".card"), function (c) {
        c.hidden = !!want && c.getAttribute("data-training") !== want;
      });
      count("filter/" + (want || "all"));
    });
  });

  // Copy buttons: data-copy="#id" copies that element's text.
  Array.prototype.forEach.call(document.querySelectorAll("[data-copy]"), function (btn) {
    btn.addEventListener("click", function () {
      var el = document.querySelector(btn.getAttribute("data-copy"));
      if (!el) return;
      var text = el.value || el.textContent;
      var done = function () { flash(btn, "Copied"); };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, function () { el.select && el.select(); });
      } else if (el.select) { el.select(); try { document.execCommand("copy"); done(); } catch (e) { /* ignore */ } }
      count("copy/" + btn.getAttribute("data-copy").slice(1));
    });
  });

  // Share buttons: the system share sheet where there is one, otherwise copy the link.
  Array.prototype.forEach.call(document.querySelectorAll("[data-share]"), function (btn) {
    btn.addEventListener("click", function () {
      var url = (document.querySelector('link[rel=canonical]') || {}).href || location.href;
      if (navigator.share) {
        navigator.share({ title: document.title, url: url }).catch(function () {});
      } else if (navigator.clipboard) {
        navigator.clipboard.writeText(url).then(function () { flash(btn, "Link copied"); });
      }
      count("share");
    });
  });

  // Activation: a visitor follows a quote to the company's own document.
  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("a.src");
    if (a) count("source-click");
  });

  // Self-test, used by scripts/e2e.mjs. It checks what a visitor relies on, derived from the page itself.
  if (/[?&]selftest=1/.test(location.search)) {
    window.addEventListener("load", function () {
      setTimeout(function () {
        var fails = [];
        var ok = function (cond, msg) { if (!cond) fails.push(msg); };
        ok(document.querySelector("h1"), "page has a heading");
        ok(document.querySelector('link[rel=canonical]'), "page has a canonical URL");
        Array.prototype.forEach.call(document.querySelectorAll('script[type="application/ld+json"]'), function (s, i) {
          try { JSON.parse(s.textContent); } catch (e) { fails.push("structured data block " + i + " parses"); }
        });
        var quotes = document.querySelectorAll("blockquote.q");
        Array.prototype.forEach.call(quotes, function (q, i) {
          var src = q.querySelector("a.src");
          ok(src && /^https?:\/\//.test(src.getAttribute("href")), "quote " + i + " links to its source");
          ok(q.textContent.trim().length > 10, "quote " + i + " has text");
        });
        if (document.querySelector(".scorebox")) {
          ok(quotes.length > 0, "scorecard shows quotes");
          ok(document.querySelector(".scorebox time"), "scorecard shows an as-of date");
          ok(document.querySelector("a.correction"), "scorecard has a correction link");
        }
        var cards = document.querySelector("#cards");
        if (cards) {
          var n = cards.querySelectorAll(".card").length;
          ok(n > 0 && n === Number(cards.getAttribute("data-count")), "home lists every scorecard");
          var first = document.querySelector("[data-filter]:not([data-filter=''])");
          if (first) {
            first.click();
            var shown = cards.querySelectorAll(".card:not([hidden])").length;
            ok(shown > 0 && shown <= n, "a filter shows a subset");
            document.querySelector("[data-filter='']").click();
            ok(cards.querySelectorAll(".card:not([hidden])").length === n, "'All' shows every card again");
          }
        }
        ok(errors.length === 0, "no script errors: " + errors.join("; "));
        var out = document.getElementById("selftest");
        out.hidden = false;
        out.setAttribute("data-selftest", fails.length ? "fail" : "pass");
        out.textContent = fails.length ? "FAIL\n" + fails.join("\n") : "PASS";
      }, 300);
    });
  }
})();
