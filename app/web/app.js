"use strict";
const $ = (id) => document.getElementById(id);
const el = (tag, text, cls) => {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  if (cls) n.className = cls;
  return n;
};
let state = "",
  documentText = "",
  busy = false,
  turn = 0;
async function api(path, body, headers) {
  const r = await fetch(
    path,
    body === undefined
      ? { cache: "no-store" }
      : {
          method: "POST",
          headers: headers || { "Content-Type": "application/json" },
          body: headers ? body : JSON.stringify(body),
        },
  );
  const d = await r.json();
  if (!r.ok)
    throw new Error(
      d.detail?.message ||
        (r.status === 413
          ? "This request is too large. Use a shorter redacted excerpt."
          : "We could not process that request. Please try again."),
    );
  return d;
}
function appendTurn(text, kind) {
  const box = el("article", undefined, "turn " + kind);
  box.append(el("div", kind === "user" ? "You" : "Pro-One", "speaker"));
  if (text) box.append(el("p", text));
  $("conversation").append(box);
  return box;
}
function populate(text) {
  $("message").value = text;
  $("message").focus();
}
function sourcePanel(sources, prefix) {
  $("source-panel").hidden = !sources.length;
  $("sources").replaceChildren();
  for (const s of sources) {
    const row = el("div", undefined, "source");
    row.id = prefix + s.number;
    const link = el("a", "[" + s.number + "] " + s.title);
    if (s.url?.startsWith("https://")) {
      link.href = s.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
    }
    row.append(
      link,
      el("small", s.issuing_authority),
      el("small", s.locator),
      el("small", s.citation),
      el("small", (s.source_type || "official source").replaceAll("_", " ")),
      el(
        "small",
        s.currentness === "certified"
          ? "Currentness certified"
          : "Currentness has not been certified",
      ),
    );
    if (s.case_metadata) {
      row.append(el("small", s.case_metadata.court + " · " + (s.case_metadata.decision_date || "Date unknown")),
        el("small", "Opinion: " + s.case_metadata.opinion_role + " · " + s.case_metadata.publication_status + " · " + s.case_metadata.precedential_status),
        el("small", "Subsequent treatment: " + s.case_metadata.subsequent_treatment));
    }
    if (s.external_identifiers) {
      row.append(el("small", "CourtListener v4 · " + (s.external_identifiers.origin === "fixture" ? "offline reconstructed fixture" : s.external_identifiers.origin)),
        el("small", "Citation identity: " + s.external_identifiers.citation_status));
    }
    if (s.enactment_metadata) {
      row.append(el("small", "Section " + s.enactment_metadata.section + " · Effective date " + (s.enactment_metadata.effective_date || "unverified")));
    }
    for (const limit of s.limitations) row.append(el("small", limit));
    $("sources").append(row);
  }
}
async function send(event) {
  event?.preventDefault();
  const message = $("message").value.trim();
  if (!message || busy) return;
  busy = true;
  $("send").disabled = true;
  $("file").disabled = true;
  $("welcome").hidden = true;
  $("suggestions").hidden = true;
  $("workspace").classList.add("active");
  appendTurn(message, "user");
  $("message").value = "";
  $("progress").textContent =
    "Understanding your question and checking authoritative sources…";
  try {
    const data = await api("/assistant/message", {
      message,
      document_text: documentText,
      conversation_state: state,
    });
    if (data.conversation_state) state = data.conversation_state;
    const box = appendTurn(data.message, "assistant");
    $("matter").replaceChildren();
    for (const [name, fact] of Object.entries(data.matter || {})) {
      if (["country", "user_type", "matter_type"].includes(name)) continue;
      const row = el("div", fact.value.replaceAll("_", " "), "fact");
      row.append(
        el(
          "small",
          name.replaceAll("_", " ") +
            " · " +
            (fact.provenance === "user_confirmed"
              ? "You confirmed"
              : fact.provenance === "candidate_classification"
              ? "Topic to research"
              : "You provided"),
        ),
      );
      $("matter").append(row);
    }
    $("matter-panel").hidden = !Object.keys(data.matter || {}).length;
    if (data.status === "confirmation_needed") {
      const yes = el("button", "Yes, that’s correct");
      yes.addEventListener("click", () => {
        populate("Yes");
        send();
      });
      const chips = el("div", undefined, "chips");
      chips.append(yes);
      box.append(chips);
    }
    if (data.response) {
      const prefix = "source-" + ++turn + "-";
      for (const notice of data.response.notices)
        box.append(el("div", notice, "notice"));
      for (const s of data.response.sections) {
        const p = el("p", s.text);
        for (const number of s.citation_numbers) {
          const a = el("a", "[" + number + "]");
          a.href = "#" + prefix + number;
          a.addEventListener("click", () =>
            sourcePanel(data.response.sources, prefix),
          );
          const sup = el("sup");
          sup.append(a);
          p.append(" ", sup);
        }
        box.append(p);
      }
      sourcePanel(data.response.sources, prefix);
      const limits = el("details");
      limits.append(el("summary", "Source limits and important notices"));
      for (const warning of data.response.warnings)
        limits.append(el("p", warning));
      box.append(limits);
      const chips = el("div", undefined, "chips");
      for (const text of data.followups || []) {
        const b = el("button", text);
        b.addEventListener("click", () => {
          populate(text);
          send();
        });
        chips.append(b);
      }
      box.append(chips);
    }
    box.scrollIntoView({ block: "nearest" });
  } catch (error) {
    appendTurn(error.message, "assistant");
  } finally {
    busy = false;
    $("send").disabled = false;
    $("file").disabled = false;
    $("progress").textContent = "";
    $("message").focus();
  }
}
$("composer").addEventListener("submit", send);
$("suggestions")
  .querySelectorAll("button")
  .forEach((b) => b.addEventListener("click", () => populate(b.textContent)));
$("new-chat").addEventListener("click", () => location.reload());
$("coverage-toggle").addEventListener("click", () => {
  $("coverage").hidden = !$("coverage").hidden;
  if (!$("coverage").hidden) $("coverage").scrollIntoView();
});
$("file").addEventListener("change", async () => {
  const file = $("file").files[0];
  if (!file) return;
  documentText = "";
  $("attachment").hidden = true;
  const types = {
    pdf: "application/pdf",
    docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    txt: "text/plain",
  };
  const type = types[file.name.split(".").pop().toLowerCase()];
  if (!type || file.size > 2 * 1024 * 1024) {
    $("progress").textContent = "Use PDF, DOCX or TXT up to 2 MB.";
    return;
  }
  busy = true;
  $("send").disabled = true;
  $("progress").textContent = "Reading your document…";
  try {
    const data = await api("/documents/extract", file, {
      "Content-Type": type,
    });
    documentText = data.text;
    $("attachment").replaceChildren(
      el("span", file.name + (data.pages ? " · " + data.pages + " pages" : "")),
    );
    const remove = el("button", "×");
    remove.type = "button";
    remove.setAttribute("aria-label", "Remove document");
    remove.addEventListener("click", () => {
      documentText = "";
      $("attachment").hidden = true;
      $("file").value = "";
    });
    $("attachment").append(remove);
    $("attachment").hidden = false;
    $("progress").textContent = data.warnings.join(" ");
    if (!$("message").value) populate("Can you explain this?");
  } catch (error) {
    $("progress").textContent = error.message;
  } finally {
    busy = false;
    $("send").disabled = false;
    $("file").value = "";
  }
});
api("/assistant/status")
  .then((data) => {
    $("demo").hidden = !data.demo;
    if (data.demo) {
      const examples = ["Try CourtListener research example", "Try premises liability example", "I received Virginia form DC-402", "My Virginia LLC SCC record"];
      $("suggestions").replaceChildren();
      for (const text of examples) {
        const button = el("button", text);
        button.addEventListener("click", () => populate(text));
        $("suggestions").append(button);
      }
    }
    if (!data.available)
      $("progress").textContent =
        "Live AI is unavailable. Please try again later.";
    for (const c of data.coverage) {
      const item = el("article");
      item.append(el("h3", c.title), el("p", c.state + " · " + c.purpose));
      $("coverage-items").append(item);
    }
    if (location.pathname === "/coverage") $("coverage").hidden = false;
  })
  .catch(() => {
    $("progress").textContent =
      "The service is unavailable. Please try again later.";
  });
