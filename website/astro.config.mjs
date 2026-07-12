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
            {
              label: 'Configuration',
              items: [
                { label: 'Overview', link: '/guides/configuration/' },
                { label: 'Profiles', link: '/guides/configuration-profiles/' },
                { label: 'Metrics', link: '/guides/configuration-metrics/' },
              ],
            },
            {
              label: 'Databases',
              items: [
                { label: 'Overview', link: '/guides/databases/' },
                { label: 'ClickHouse', link: '/guides/databases-clickhouse/' },
                { label: 'PostgreSQL', link: '/guides/databases-postgres/' },
                { label: 'MySQL', link: '/guides/databases-mysql/' },
                { label: 'DuckDB', link: '/guides/databases-duckdb/' },
              ],
            },
            {
              label: 'Alerting',
              items: [
                { label: 'Overview', link: '/guides/alerting/' },
                { label: 'Channels', link: '/guides/alerting-channels/' },
                { label: 'Multiple alert blocks', link: '/guides/alerting-multiple-blocks/' },
                { label: 'Cooldown & recovery', link: '/guides/alerting-cooldown-recovery/' },
                { label: 'No-data & errors', link: '/guides/alerting-no-data-errors/' },
                { label: 'Templates & mentions', link: '/guides/alerting-templates-mentions/' },
                { label: 'Patterns', link: '/guides/alerting-patterns/' },
                { label: 'Reading an alert', link: '/guides/reading-alerts/' },
              ],
            },
            // Single-page topics — kept as standalone leaves after the multi-page groups
            // (a child is a group iff it owns 2+ pages). "Auto-tuning" stays a peer of
            // "Detectors", not nested: it's a separate command/workflow with its own
            // Reference entry, and nesting would collide with the Reference "Detectors" group.
            { label: 'Detectors', link: '/guides/detectors/' },
            { label: 'Auto-tuning', link: '/guides/autotuning/' },
            { label: 'Tuning (manual)', link: '/guides/tuning/' },
            { label: 'Project UI', link: '/guides/project-ui/' },
            { label: 'Semantic layer (OSI)', link: '/guides/osi/' },
            { label: 'Visualizing results', link: '/guides/visualizing-results/' },
          ],
        },
        {
          label: 'Reference',
          items: [
            { label: 'CLI', link: '/reference/cli/' },
            { label: 'Auto-tune', link: '/reference/autotune/' },
            { label: 'Internal tables', link: '/reference/internal-tables/' },
            {
              // Renamed from "Detectors" to disambiguate from the Guides > Detectors page.
              label: 'Detector reference',
              items: [
                { label: 'Shared parameters', link: '/reference/detectors/shared-parameters/' },
                { label: 'MAD', link: '/reference/detectors/mad/' },
                { label: 'Z-Score', link: '/reference/detectors/zscore/' },
                { label: 'IQR', link: '/reference/detectors/iqr/' },
                { label: 'Manual Bounds', link: '/reference/detectors/manual_bounds/' },
                { label: 'Autoreg', link: '/reference/detectors/autoreg/' },
              ],
            },
          ],
        },
        { label: 'Examples', link: '/examples/' },
        {
          label: 'For developers',
          items: [
            { label: 'Architecture', link: '/development/architecture/' },
            { label: 'Contributing', link: '/development/contributing/' },
            { label: 'Design & brand', link: '/development/design/' },
          ],
        },
        { label: 'Changelog', link: '/changelog/' },
      ],
    }),
  ],
});
