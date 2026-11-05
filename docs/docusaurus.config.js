const { themes } = require("prism-react-renderer");

/** @type {import('@docusaurus/types').Config} */
module.exports = {
  title: "CAIPE Sandbox",
  tagline: "Developer micro VMs on Kubernetes.",
  favicon: "img/caipe-sandbox-logo.svg",
  url: "https://caipe-io.github.io",
  baseUrl: process.env.DOCS_BASE_URL || "/",
  organizationName: "caipe-io",
  projectName: "caipe-sandbox",
  trailingSlash: false,
  onBrokenLinks: "throw",
  markdown: {
    mermaid: true,
    hooks: { onBrokenMarkdownLinks: "throw" },
  },
  themes: ["@docusaurus/theme-mermaid"],
  presets: [
    [
      "classic",
      {
        docs: {
          path: "content",
          routeBasePath: "guide",
          sidebarPath: require.resolve("./sidebars.js"),
        },
        blog: false,
        theme: { customCss: require.resolve("./src/css/custom.css") },
      },
    ],
  ],
  themeConfig: {
    colorMode: { defaultMode: "light", respectPrefersColorScheme: true },
    navbar: {
      title: "CAIPE Sandbox",
      logo: { alt: "CAIPE Sandbox", src: "img/caipe-sandbox-logo.svg" },
      items: [
        {
          type: "docSidebar",
          sidebarId: "guide",
          label: "Guide",
          position: "left",
        },
        {
          to: "/guide/architecture",
          label: "Architecture",
          position: "left",
        },
        {
          to: "/guide/configuration",
          label: "Configuration",
          position: "left",
        },
        { to: "/guide/code-map", label: "Code map", position: "left" },
        { to: "/guide/slides", label: "Slides", position: "left" },
        {
          href: "https://github.com/caipe-io/caipe-sandbox",
          label: "GitHub",
          position: "right",
        },
      ],
    },
    footer: {
      style: "light",
      links: [
        {
          title: "Learn",
          items: [
            { label: "Overview", to: "/guide/overview" },
            { label: "Architecture", to: "/guide/architecture" },
            { label: "Micro VM lifecycle", to: "/guide/workspaces" },
          ],
        },
        {
          title: "Explore",
          items: [
            { label: "Configuration explorer", to: "/guide/configuration" },
            { label: "Code map", to: "/guide/code-map" },
            { label: "Presentation", to: "/guide/slides" },
          ],
        },
        {
          title: "Project",
          items: [
            {
              label: "GitHub",
              href: "https://github.com/caipe-io/caipe-sandbox",
            },
            {
              label: "Apache 2.0 license",
              href: "https://github.com/caipe-io/caipe-sandbox/blob/main/LICENSE",
            },
          ],
        },
      ],
      copyright: "CAIPE Sandbox · Apache 2.0",
    },
    prism: {
      theme: themes.github,
      darkTheme: themes.dracula,
      additionalLanguages: ["bash", "yaml", "python"],
    },
  },
};
