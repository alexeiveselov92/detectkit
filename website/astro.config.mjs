// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

// Brand fonts (mirrors the brand guide: Schibsted Grotesk + JetBrains Mono).
const fontHead = [
  { tag: 'link', attrs: { rel: 'preconnect', href: 'https://fonts.googleapis.com' } },
  { tag: 'link', attrs: { rel: 'preconnect', href: 'https://fonts.gstatic.com', crossorigin: true } },
  {
    tag: 'link',
    attrs: {
      rel: 'stylesheet',
      href: 'https://fonts.googleapis.com/css2?family=Schibsted+Grotesk:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap',
    },
  },
];

// https://astro.build/config
export default defineConfig({
  site: 'https://dtk.pipelab.dev',
  integrations: [
    starlight({
      title: 'detectkit',
      description:
        'Time-series anomaly detection and alerting with a dbt-like project layout. SQL + YAML, one command.',
      logo: { src: './src/assets/logo.svg', alt: 'detectkit' },
      favicon: '/favicon.svg',
      customCss: ['./src/styles/brand.css'],
      head: fontHead,
      // Brand uses dark terminal surfaces everywhere — keep code blocks dark on both themes.
      expressiveCode: {
        themes: ['github-dark'],
        // The docs use a ```jinja2 fence; Shiki bundles it as "jinja".
        shiki: { langAlias: { jinja2: 'jinja' } },
      },
      social: [
        { icon: 'github', label: 'GitHub', href: 'https://github.com/alexeiveselov92/detectkit' },
      ],
      sidebar: [
        { label: 'Overview', link: '/overview/' },
        {
          label: 'Getting Started',
          items: [
            { label: 'Installation', link: '/getting-started/installation/' },
            { label: 'Quickstart', link: '/getting-started/quickstart/' },
          ],
        },
        {
          label: 'Guides',
          items: [
            { label: 'Configuration', link: '/guides/configuration/' },
            { label: 'Detectors', link: '/guides/detectors/' },
            { label: 'Alerting', link: '/guides/alerting/' },
          ],
        },
        {
          label: 'Reference',
          items: [
            { label: 'CLI', link: '/reference/cli/' },
            {
              label: 'Detectors',
              items: [
                { label: 'MAD', link: '/reference/detectors/mad/' },
                { label: 'Z-Score', link: '/reference/detectors/zscore/' },
                { label: 'IQR', link: '/reference/detectors/iqr/' },
                { label: 'Manual Bounds', link: '/reference/detectors/manual_bounds/' },
              ],
            },
          ],
        },
        { label: 'Examples', link: '/examples/' },
        { label: 'Changelog', link: '/changelog/' },
      ],
    }),
  ],
});
