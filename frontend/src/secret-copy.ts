/** Copy one-time credentials on the few account pages that expose them. */

document
  .querySelectorAll<HTMLButtonElement>("[data-copy-target], [data-copy-targets]")
  .forEach((button) => {
    button.addEventListener("click", () => {
      const targetIds = (button.dataset.copyTargets ?? button.dataset.copyTarget ?? "")
        .split(",")
        .map((value) => value.trim())
        .filter(Boolean);
      const text = targetIds
        .map((targetId) => document.getElementById(targetId)?.textContent?.trim())
        .filter(Boolean)
        .join("\n");
      if (!text || !navigator.clipboard) return;

      void navigator.clipboard.writeText(text).then(() => {
        const previous = button.textContent;
        button.textContent = "copied";
        window.setTimeout(() => {
          button.textContent = previous;
        }, 2000);
      });
    });
  });
