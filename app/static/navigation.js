/* Comportamento compartilhado do logout; mantém sessão e CSRF no backend. */
(() => {
    const button = document.getElementById("logout");
    if (!button) return;
    button.addEventListener("click", async () => {
        const status = document.getElementById("navigation-status");
        const csrf = document.cookie.split("; ").find(value => value.startsWith("dba_tools_csrf="))?.slice("dba_tools_csrf=".length) || "";
        button.disabled = true;
        button.textContent = "Saindo...";
        if (status) status.textContent = "";
        try {
            const response = await fetch("/auth/logout", {
                method: "POST", headers: {"X-CSRF-Token": decodeURIComponent(csrf)}, credentials: "same-origin"
            });
            if (response.ok) window.location.assign("/login");
            else if (status) status.textContent = "Não foi possível sair. Tente novamente.";
        } catch (_) {
            if (status) status.textContent = "Falha de conexão ao sair. Tente novamente.";
        } finally {
            button.disabled = false;
            button.textContent = "Sair";
        }
    });
})();
