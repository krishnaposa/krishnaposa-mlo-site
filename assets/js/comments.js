(function () {
    // ----- CONFIG -----
    const API_BASE = "https://blog-comments-ffd9fae6hmcta7e4.eastus2-01.azurewebsites.net/comments"; // set your app URL
    const PATH = location.pathname;

    async function loadComments() {
        const res = await fetch(`${API_BASE}/comments?path=${encodeURIComponent(PATH)}`);
        const data = await res.json();
        const list = document.getElementById("comment-list");
        list.innerHTML = "";
        if (!data.ok) { list.innerHTML = "<p class='small'>Error loading comments.</p>"; return; }
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
    }

    async function postComment(evt) {
        evt.preventDefault();
        const status = document.getElementById("c-status");
        status.textContent = "Submitting…";
        const payload = {
            path: PATH,
            name: document.getElementById("c-name").value.trim(),
            email: document.getElementById("c-email").value.trim(),
            message: document.getElementById("c-message").value.trim()
        };
        const res = await fetch(`${API_BASE}/comments`, {
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
    }

    window.CommentWidget = {
        init: function () {
            document.getElementById("comment-form").addEventListener("submit", postComment);
            loadComments();
        }
    };
})();
