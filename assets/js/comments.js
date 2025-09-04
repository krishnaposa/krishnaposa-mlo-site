<script>
(function () {
  const API_BASE = "https://blog-comments-ffd9fae6hmcta7e4.eastus2-01.azurewebsites.net";
  const PATH = location.pathname;

  async function loadComments() {
    const list = document.getElementById("comment-list");
    try {
      const res = await fetch(`${API_BASE}/comments?path=${encodeURIComponent(PATH)}`);
      const data = await res.json();
      list.innerHTML = "";
      if (!data.ok) { list.innerHTML = "<p class='small'>Couldn’t load comments.</p>"; return; }
      if (!data.comments.length) { list.innerHTML = "<p class='small'>No comments yet. Be the first!</p>"; return; }
      data.comments.forEach(c => {
        const el = document.createElement("div");
        el.className = "card";
        el.innerHTML = `
          <div style="font-weight:600">${c.name}</div>
          <div class="small" style="color:#666">${new Date(c.createdAt).toLocaleString()}</div>
          <p style="margin:.5rem 0 0; white-space:pre-wrap">${c.message}</p>`;
        list.appendChild(el);
      });
    } catch {
      list.innerHTML = "<p class='small'>Couldn’t load comments.</p>";
    }
  }

  let posting = false;
  async function postComment(evt) {
    evt.preventDefault();
    if (posting) return;
    posting = true;

    const btn = evt.submitter || document.querySelector("#comment-form button[type=submit]");
    const status = document.getElementById("c-status");
    const payload = {
      path: PATH,
      name: document.getElementById("c-name").value.trim(),
      email: document.getElementById("c-email").value.trim(),
      message: document.getElementById("c-message").value.trim()
    };
    if (!payload.name || !payload.message) {
      status.textContent = "Name and comment are required.";
      posting = false; return;
    }

    btn?.setAttribute("disabled", "disabled");
    status.textContent = "Submitting…";

    try {
      const res = await fetch(`${API_BASE}/comments/post`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (res.ok && data.ok) {
        status.textContent = "Thanks! Your comment is pending moderation.";
        document.getElementById("comment-form").reset();
      } else {
        status.textContent = data.error || "Error submitting comment.";
      }
    } catch {
      status.textContent = "Network error submitting comment.";
    } finally {
      btn?.removeAttribute("disabled");
      posting = false;
    }
  }

  window.CommentWidget = {
    init() {
      const form = document.getElementById("comment-form");
      if (form) form.addEventListener("submit", postComment);
      loadComments();
    }
  };
})();
</script>