// Wires project-page interactions to the JSON endpoints from app.py.
async function postJSON(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  return r.json();
}

const uploadForm = document.querySelector("[data-upload-form]");
if (uploadForm) {
  uploadForm.addEventListener("submit", (ev) => {
    // Async upload: the AI call runs in a server-side background job and we
    // poll it, so neither the proxy nor the worker can time the request out.
    ev.preventDefault();
    const loading = document.querySelector("[data-upload-loading]");
    const submit = document.querySelector("[data-upload-submit]");
    if (submit) {
      submit.disabled = true;
      submit.classList.add("opacity-60", "cursor-wait");
      submit.textContent = "Generating...";
    }

    const restore = (msg) => {
      if (msg) alert(msg);
      if (loading) {
        loading.classList.add("hidden");
        loading.classList.remove("flex");
      }
      if (submit) {
        submit.disabled = false;
        submit.classList.remove("opacity-60", "cursor-wait");
        submit.textContent = "Generate tracker";
      }
    };

    fetch("/upload", {
      method: "POST",
      headers: { "X-Async": "1" },
      body: new FormData(uploadForm),
    })
      .then((r) => r.json())
      .then((r) => {
        if (!r.ok) return restore(r.error || "Upload failed.");
        const poll = () => {
          fetch(`/upload/job/${r.job_id}`)
            .then((p) => p.json())
            .then((job) => {
              if (job.status === "done") {
                window.location = `/project/${job.project_id}`;
              } else if (job.status === "error") {
                restore(job.error || "Extraction failed — please try again.");
              } else {
                setTimeout(poll, 2500);
              }
            })
            .catch(() => setTimeout(poll, 4000)); // transient blip: keep polling
        };
        setTimeout(poll, 4000);
      })
      .catch(() => restore("Could not reach the server — try again."));

    if (!loading) return;
    loading.classList.remove("hidden");
    loading.classList.add("flex");

    // Stage checklist: tick stages off on a schedule that mirrors the
    // typical ~25s extraction, so the wait reads as visible work.
    const title = loading.querySelector("[data-stage-title]");
    const stages = [...loading.querySelectorAll("[data-stages] li")];
    const start = Date.now();
    stages.forEach((li) => {
      const at = Number(li.dataset.at) * 1000;
      setTimeout(() => {
        stages.forEach((other) => {
          if (Number(other.dataset.at) * 1000 < at) {
            other.classList.remove("active");
            other.classList.add("done");
          }
        });
        li.classList.add("active");
        if (title) title.textContent = li.textContent + "…";
      }, at);
    });

    // Progress bar: ease toward 94% and wait there — the redirect ends it.
    const barFill = loading.querySelector("[data-progress]");
    if (barFill) {
      const tick = () => {
        const t = (Date.now() - start) / 1000;
        barFill.style.width = (94 * (1 - Math.exp(-t / 12))).toFixed(1) + "%";
        if (t < 120) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    }
  });
}

document.addEventListener("change", (e) => {
  if (e.target.classList.contains("js-status")) {
    const li = e.target.closest("[data-item-id]");
    const status = e.target.checked ? "done" : "todo";
    postJSON(`/item/${li.dataset.itemId}/status`, { status }).then(() =>
      window.location.reload()
    );
  }
  if (e.target.classList.contains("js-everyday-status")) {
    const li = e.target.closest("[data-everyday-id]");
    const status = e.target.checked ? "done" : "todo";
    postJSON(`/everyday/${li.dataset.everydayId}/status`, { status }).then(() =>
      window.location.reload()
    );
  }
  if (e.target.classList.contains("js-everyday-day")) {
    const cb = e.target;
    // Persist the per-day completion; no reload so the grid stays put.
    postJSON(`/everyday/${cb.dataset.everydayId}/day`, {
      day: cb.dataset.day,
      done: cb.checked,
    });
  }
});

// If the user hasn't granted calendar access yet, send them through the
// one-time incremental OAuth consent and bring them back here.
function gcalConnect() {
  window.location =
    "/auth/calendar?next=" + encodeURIComponent(window.location.pathname);
}

document.addEventListener("click", (e) => {
  const gItem = e.target.closest(".js-gcal-item");
  if (gItem) {
    const li = gItem.closest("[data-item-id]");
    const id = gItem.dataset.itemId || (li && li.dataset.itemId);
    gItem.disabled = true;
    const old = gItem.textContent;
    gItem.textContent = "Adding…";
    postJSON(`/item/${id}/gcal`).then((r) => {
      if (r.connect) return gcalConnect();
      gItem.textContent = r.ok ? "✓ Added to Google Calendar" : old;
      gItem.disabled = !!r.ok;
      if (!r.ok) alert(r.error || "Could not add to Google Calendar");
    });
    return;
  }
  const gProj = e.target.closest(".js-gcal-project");
  if (gProj) {
    gProj.disabled = true;
    const old = gProj.textContent;
    gProj.textContent = "Syncing…";
    postJSON(`/project/${gProj.dataset.projectId}/gcal`).then((r) => {
      if (r.connect) return gcalConnect();
      gProj.disabled = false;
      gProj.textContent = old;
      alert(r.ok ? `Added ${r.added} task(s) to your Google Calendar.`
                 : (r.error || "Could not sync to Google Calendar"));
    });
    return;
  }
  const delProj = e.target.closest(".js-delete-project");
  if (delProj) {
    if (confirm("Delete this entire project and all its tasks? This cannot be undone.")) {
      postJSON(`/project/${delProj.dataset.projectId}/delete`).then(() => {
        window.location = "/projects";
      });
    }
    return;
  }
  // toggle todo <-> in_progress (done stays on the checkbox)
  const prog = e.target.closest(".js-progress");
  if (prog) {
    const li = prog.closest("[data-item-id]");
    const status = li.dataset.status === "in_progress" ? "todo" : "in_progress";
    postJSON(`/item/${li.dataset.itemId}/status`, { status }).then(() =>
      window.location.reload()
    );
    return;
  }
  // closest() (not e.target.classList) so clicks on the SVGs inside these
  // buttons still resolve to the button.
  const del = e.target.closest(".js-delete");
  if (del) {
    const li = del.closest("[data-item-id]");
    if (confirm("Delete this item?")) {
      postJSON(`/item/${li.dataset.itemId}/delete`).then(() =>
        window.location.reload()
      );
    }
    return;
  }
  const addItem = e.target.closest(".js-add-item");
  if (addItem) {
    const title = prompt("New item title?");
    if (title) {
      postJSON(`/phase/${addItem.dataset.phaseId}/item`, { title }).then(() =>
        window.location.reload()
      );
    }
    return;
  }
  const addPhase = e.target.closest(".js-add-phase");
  if (addPhase) {
    const name = prompt("New phase name?");
    if (name) {
      postJSON(`/project/${addPhase.dataset.projectId}/phase`, { name }).then(
        () => window.location.reload()
      );
    }
    return;
  }
  const delEveryday = e.target.closest(".js-delete-everyday");
  if (delEveryday) {
    const li = delEveryday.closest("[data-everyday-id]");
    if (confirm("Delete this everyday item?")) {
      postJSON(`/everyday/${li.dataset.everydayId}/delete`).then(() =>
        window.location.reload()
      );
    }
    return;
  }
  const addEveryday = e.target.closest(".js-add-everyday");
  if (addEveryday) {
    const title = prompt("New everyday item?");
    if (title) {
      postJSON(`/project/${addEveryday.dataset.projectId}/everyday`, {
        title,
      }).then(() => window.location.reload());
    }
  }
});
