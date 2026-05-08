const signinForm = document.querySelector(".signin-form");

if (signinForm) {
  const identifierInput = signinForm.querySelector("input[type='text']");
  const passwordInput = signinForm.querySelector("input[type='password']");
  const submitButton = signinForm.querySelector("button[type='submit']");
  const message = document.getElementById("signin-message");

  signinForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    submitButton.disabled = true;
    message.textContent = "Signing in...";

    try {
      const response = await fetch("/api/signin", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          identifier: identifierInput.value.trim(),
          password: passwordInput.value,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        message.textContent = data.error || "Unable to sign in.";
        return;
      }

      localStorage.setItem("netflixCloneUser", JSON.stringify(data.user));
      if (data.session_id) {
        localStorage.setItem("netflixCloneSession", String(data.session_id));
      }
      message.textContent = `Welcome, ${data.user.full_name}!`;
      setTimeout(() => {
        window.location.href = "/browse";
      }, 1200);
    } catch (error) {
      message.textContent = "Network error. Please try again.";
    } finally {
      submitButton.disabled = false;
    }
  });
}
