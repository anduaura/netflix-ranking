// Donation/support config. Fill in any handles you want to enable;
// leave the others as empty strings and they'll be hidden in the UI.
// If every value is empty, the "Support" button disappears entirely.
window.SITE_CONFIG = {
  support: {
    github_sponsors: "anduaura",   // -> https://github.com/sponsors/anduaura
    buy_me_a_coffee: "",   // e.g. "anduaura"           -> https://www.buymeacoffee.com/anduaura
    kofi:            "",   // e.g. "anduaura"           -> https://ko-fi.com/anduaura
    paypal:          "",   // e.g. "anduaura"           -> https://www.paypal.com/paypalme/anduaura
    custom: {
      label: "",           // free-form label, e.g. "Stripe"
      url:   ""            // any https:// URL
    }
  },
  feedback: {
    // Where the "Send by email" button targets. Leave blank to hide.
    email: "andu.ucsd@gmail.com",
    // Where "Open as GitHub issue" targets. Leave blank to hide.
    // Format: "owner/repo".
    github_repo: "anduaura/netflix-ranking",
  },
};
