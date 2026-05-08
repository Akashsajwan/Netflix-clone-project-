const signupForm = document.querySelector(".signup-form");

if (signupForm) {
  const emailInput = signupForm.querySelector("input[type='email']");
  const passwordInput = signupForm.querySelector("input[type='password']");
  const fullNameInput = signupForm.querySelector("input[type='text']");
  const planInput = document.getElementById("plan-select");
  const submitButton = signupForm.querySelector("button[type='submit']");
  const message = document.getElementById("signup-message");

  signupForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    submitButton.disabled = true;
    message.textContent = "Creating account...";

    try {
      const response = await fetch("/api/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: emailInput.value.trim(),
          password: passwordInput.value,
          full_name: fullNameInput.value.trim(),
          plan: planInput ? planInput.value : "free",
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        message.textContent = data.error || "Unable to create account.";
        return;
      }

      message.textContent = "Account created. Redirecting to sign in...";
      signupForm.reset();
      setTimeout(() => {
        window.location.href = "/signin";
      }, 1000);
    } catch (error) {
      message.textContent = "Network error. Please try again.";
    } finally {
      submitButton.disabled = false;
    }
  });
}
