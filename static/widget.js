/*
 * Helpdesk embeddable widget.
 *
 * Usage on any HTML page:
 *   <div id="helpdesk"></div>
 *   <script src="https://YOUR-APP.up.railway.app/widget.js"></script>
 *
 * Optional config via attributes on the <script> tag:
 *   data-target="#helpdesk"   CSS selector of the mount element (default #helpdesk)
 *   data-title="Central de Dúvidas"
 *
 * Renders inside a Shadow DOM so the host page's CSS can't leak in or out.
 */
var STYLE =
  "<style>" +
  ".hd{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#1a1a1a;" +
  "max-width:720px;margin:0 auto;line-height:1.5}" +
  ".hd *{box-sizing:border-box}" +
  ".hd-head h2{margin:0 0 .6rem;font-size:1.4rem}" +
  ".hd-search{width:100%;padding:.7rem .9rem;font-size:1rem;border:1px solid #ccc;" +
  "border-radius:8px;margin-bottom:1rem}" +
  ".hd-search:focus{outline:2px solid #2563eb;border-color:#2563eb}" +
  ".hd-sub{font-size:.8rem;text-transform:uppercase;letter-spacing:.05em;color:#666;margin:1rem 0 .5rem}" +
  ".hd-groups,.hd-list{list-style:none;padding:0;margin:0}" +
  ".hd-groups li,.hd-list li{margin:0 0 .4rem}" +
  ".hd-groups a{display:flex;justify-content:space-between;align-items:center;" +
  "padding:.7rem .9rem;background:#f5f6f8;border-radius:8px;text-decoration:none;color:#1a1a1a}" +
  ".hd-groups a:hover{background:#e9ebf0}" +
  ".hd-count{background:#2563eb;color:#fff;border-radius:999px;padding:.05rem .55rem;font-size:.8rem}" +
  ".hd-list a{display:block;padding:.7rem .9rem;background:#f5f6f8;border-radius:8px;" +
  "text-decoration:none;color:#1a1a1a}" +
  ".hd-list a:hover{background:#e9ebf0}" +
  ".hd-tag{display:inline-block;background:#e0e7ff;color:#3730a3;border-radius:6px;" +
  "padding:.05rem .5rem;font-size:.75rem;margin-left:.5rem;text-decoration:none}" +
  ".hd-snippet{font-size:.9rem;color:#555;margin-top:.3rem}" +
  ".hd-snippet b{background:#fde68a}" +
  ".hd-by{display:block;font-size:.8rem;color:#888;margin-top:.2rem}" +
  ".hd-back{display:inline-block;margin-bottom:.8rem;color:#2563eb;text-decoration:none;font-size:.9rem}" +
  ".hd-q h3{margin:.2rem 0 .5rem;font-size:1.25rem}" +
  ".hd-qbody{white-space:pre-wrap}" +
  ".hd-a{background:#f5f6f8;border-radius:8px;padding:.8rem .9rem;margin:.5rem 0}" +
  ".hd-a p{margin:.2rem 0;white-space:pre-wrap}" +
  ".hd-accepted{background:#ecfdf5;border:1px solid #a7f3d0}" +
  ".hd-check{color:#059669;font-size:.8rem;font-weight:600}" +
  ".hd-loading,.hd-empty{color:#888;padding:1rem 0}" +
  ".hd-ask{margin-top:.8rem;padding:.9rem;background:#f5f6f8;border-radius:8px}" +
  ".hd-ask p{margin:0 0 .6rem;font-size:.9rem;color:#444}" +
  ".hd-ask input,.hd-ask textarea{width:100%;padding:.5rem .6rem;font:inherit;" +
  "border:1px solid #ccc;border-radius:6px;box-sizing:border-box;margin-bottom:.5rem}" +
  ".hd-ask textarea{min-height:4rem}" +
  ".hd-ask button{background:#2563eb;color:#fff;border:none;padding:.5rem 1rem;" +
  "border-radius:6px;cursor:pointer;font:inherit}" +
  ".hd-ask button:hover{opacity:.9}" +
  ".hd-ask .hd-ok{color:#059669;font-size:.85rem;margin-top:.5rem}" +
  "</style>";

var COORD_EMAIL = "faunadobrasilctfb@gmail.com";

(function () {
  var script = document.currentScript;
  // API base = origin the widget.js was served from.
  var apiBase = new URL(script.src).origin;
  var targetSel = script.getAttribute("data-target") || "#helpdesk";
  var title = script.getAttribute("data-title") || "Central de Dúvidas";

  var mount = document.querySelector(targetSel);
  if (!mount) {
    console.error("[helpdesk] mount element not found:", targetSel);
    return;
  }

  var root = mount.attachShadow({ mode: "open" });
  root.innerHTML = STYLE + '<div class="hd"></div>';
  var el = root.querySelector(".hd");

  function api(path) {
    return fetch(apiBase + path).then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.json();
    });
  }

  function esc(s) {
    var d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }

  // ---- routing via URL hash: #helpdesk/q/123 or #helpdesk/g/slug ----
  function parseHash() {
    var m = /#helpdesk\/(q|g)\/([^/]+)/.exec(location.hash);
    return m ? { kind: m[1], id: decodeURIComponent(m[2]) } : null;
  }
  function go(hash) {
    location.hash = hash;
  }

  function render() {
    var route = parseHash();
    if (route && route.kind === "q") return renderQuestion(route.id);
    if (route && route.kind === "g") return renderGroup(route.id);
    return renderHome();
  }

  function shell(inner) {
    el.innerHTML =
      '<header class="hd-head"><h2>' +
      esc(title) +
      '</h2><input class="hd-search" type="search" ' +
      'placeholder="Buscar dúvidas..." autocomplete="off"></header>' +
      '<div class="hd-body">' +
      inner +
      "</div>";
    var input = el.querySelector(".hd-search");
    var t;
    input.addEventListener("input", function () {
      clearTimeout(t);
      var q = input.value.trim();
      t = setTimeout(function () {
        if (q.length < 2) {
          if (!parseHash()) renderHomeBody();
          return;
        }
        api("/api/search?q=" + encodeURIComponent(q)).then(function (results) {
          renderResults(results, q);
        });
      }, 250);
    });
    return input;
  }

  function renderHome() {
    shell("");
    renderHomeBody();
  }

  function renderHomeBody() {
    var body = el.querySelector(".hd-body");
    body.innerHTML = '<div class="hd-loading">Carregando assuntos...</div>';
    api("/api/groups").then(function (groups) {
      if (!groups.length) {
        body.innerHTML = '<p class="hd-empty">Nenhum conteúdo ainda.</p>';
        return;
      }
      body.innerHTML =
        '<h3 class="hd-sub">Assuntos</h3><ul class="hd-groups">' +
        groups
          .map(function (g) {
            return (
              '<li><a href="#helpdesk/g/' +
              esc(g.slug) +
              '">' +
              esc(g.name) +
              '<span class="hd-count">' +
              (g.question_count || 0) +
              "</span></a></li>"
            );
          })
          .join("") +
        "</ul>";
    });
  }

  // Bold the query's words wherever they occur in already-escaped text,
  // so matches are visible even when they came from typo/similarity
  // matching rather than full-text search (which ts_headline highlights
  // on its own).
  function highlight(escapedText, q) {
    var words = (q || "")
      .trim()
      .split(/\s+/)
      .filter(function (w) { return w.length >= 2; })
      .map(function (w) { return w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); });
    if (!words.length) return escapedText;
    var re = new RegExp("(" + words.join("|") + ")", "gi");
    return escapedText.replace(re, "<b>$1</b>");
  }

  function renderResults(results, q) {
    var body = el.querySelector(".hd-body");
    if (!results.length) {
      body.innerHTML =
        '<p class="hd-empty">Nada encontrado.</p>' + askForm(q || "");
      wireAskForm(q || "");
      return;
    }
    body.innerHTML =
      '<ul class="hd-list">' +
      results
        .map(function (r) {
          return (
            '<li><a href="#helpdesk/q/' +
            r.id +
            '"><strong>' +
            highlight(esc(r.title), q) +
            "</strong>" +
            (r.group_name
              ? '<span class="hd-tag">' + esc(r.group_name) + "</span>"
              : "") +
            '<div class="hd-snippet">' +
            (r.snippet || "") +
            "</div></a></li>"
          );
        })
        .join("") +
      "</ul>";
  }

  // ---- ask-the-coordinators fallback when search finds nothing ----
  function askForm(q) {
    return (
      '<div class="hd-ask"><p>Não achou sua resposta? Envie a pergunta para a coordenação.</p>' +
      '<input class="hd-ask-title" placeholder="Sua pergunta" value="' +
      esc(q).replace(/"/g, "&quot;") +
      '"><textarea class="hd-ask-body" placeholder="Detalhes (opcional)"></textarea>' +
      '<input class="hd-ask-author" placeholder="Seu nome ou e-mail (opcional)">' +
      '<button class="hd-ask-send">Enviar para coordenação</button>' +
      '<div class="hd-ask-msg"></div></div>'
    );
  }

  function wireAskForm() {
    var box = el.querySelector(".hd-ask");
    if (!box) return;
    box.querySelector(".hd-ask-send").addEventListener("click", function () {
      var title = box.querySelector(".hd-ask-title").value.trim();
      var qbody = box.querySelector(".hd-ask-body").value.trim();
      var author = box.querySelector(".hd-ask-author").value.trim();
      var msg = box.querySelector(".hd-ask-msg");
      if (!title) {
        msg.textContent = "Escreva a pergunta.";
        return;
      }
      fetch(apiBase + "/api/questions/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: title, body: qbody || null, author: author || null }),
      })
        .then(function (r) {
          if (!r.ok) throw new Error();
          var subject = encodeURIComponent("Pergunta sem resposta: " + title);
          var mailBody = encodeURIComponent(
            title + (qbody ? "\n\n" + qbody : "") + (author ? "\n\n— " + author : "")
          );
          window.open(
            "mailto:" + COORD_EMAIL + "?subject=" + subject + "&body=" + mailBody,
            "_blank"
          );
          msg.className = "hd-ok";
          msg.textContent = "Enviada! A coordenação vai responder em breve.";
          box.querySelector(".hd-ask-send").disabled = true;
        })
        .catch(function () {
          msg.textContent = "Erro ao enviar. Tente novamente.";
        });
    });
  }

  function renderGroup(slug) {
    shell('<div class="hd-loading">Carregando...</div>');
    api("/api/groups/" + encodeURIComponent(slug) + "/questions").then(function (
      qs
    ) {
      var body = el.querySelector(".hd-body");
      body.innerHTML =
        '<a class="hd-back" href="#helpdesk">&larr; Voltar</a>' +
        (qs.length
          ? '<ul class="hd-list">' +
            qs
              .map(function (q) {
                return (
                  '<li><a href="#helpdesk/q/' +
                  q.id +
                  '"><strong>' +
                  esc(q.title) +
                  "</strong>" +
                  (q.author
                    ? '<span class="hd-by">' + esc(q.author) + "</span>"
                    : "") +
                  "</a></li>"
                );
              })
              .join("") +
            "</ul>"
          : '<p class="hd-empty">Sem perguntas neste assunto.</p>');
    });
  }

  function renderQuestion(id) {
    shell('<div class="hd-loading">Carregando...</div>');
    api("/api/questions/" + encodeURIComponent(id)).then(function (data) {
      var q = data.question;
      var body = el.querySelector(".hd-body");
      body.innerHTML =
        '<a class="hd-back" href="#helpdesk">&larr; Voltar</a>' +
        '<article class="hd-q"><h3>' +
        esc(q.title) +
        "</h3>" +
        (q.group_slug
          ? '<a class="hd-tag" href="#helpdesk/g/' +
            esc(q.group_slug) +
            '">' +
            esc(q.group_name) +
            "</a>"
          : "") +
        (q.body ? '<p class="hd-qbody">' + esc(q.body) + "</p>" : "") +
        (q.author ? '<p class="hd-by">Perguntado por ' + esc(q.author) + "</p>" : "") +
        '<h4 class="hd-sub">Respostas</h4>' +
        (data.answers.length
          ? data.answers
              .map(function (a) {
                return (
                  '<div class="hd-a' +
                  (a.is_accepted ? " hd-accepted" : "") +
                  '">' +
                  (a.is_accepted ? '<span class="hd-check">✓ melhor resposta</span>' : "") +
                  '<p>' +
                  esc(a.body) +
                  "</p>" +
                  (a.author ? '<span class="hd-by">' + esc(a.author) + "</span>" : "") +
                  "</div>"
                );
              })
              .join("")
          : '<p class="hd-empty">Sem respostas ainda.</p>') +
        "</article>";
    }).catch(function () {
      el.querySelector(".hd-body").innerHTML =
        '<a class="hd-back" href="#helpdesk">&larr; Voltar</a>' +
        '<p class="hd-empty">Pergunta não encontrada.</p>';
    });
  }

  window.addEventListener("hashchange", function () {
    if (parseHash() || location.hash === "" || location.hash === "#helpdesk")
      render();
  });
  render();
})();
