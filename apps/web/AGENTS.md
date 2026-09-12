# Repository Guidelines

Whatever action you can do by yourself, please do yourself. This includes starting apps and verification.

## Project Structure & Module Organization

This directory contains the Next.js + TypeScript frontend inside the WaspadAI monorepo. Treat `../../docs/frontend/context.md` as the product source of truth.

- `src/app/` for Next.js routes, layouts, and page-level UI.
- `src/components/` for reusable React components.
- `src/lib/` for shared utilities, data shaping, and verification helpers.
- `tests/` for tests that mirror the `src/` structure.
- `public/` for static images and icons.

Website scope is Home, Chat, and About. Prefer `src/app/page.tsx`, `src/app/chat/page.tsx`, and `src/app/about/page.tsx`.

## Build, Test, and Development Commands

Use root-level package scripts once `package.json` is added.

- `npm install` installs project dependencies.
- `npm run dev` starts a local development server.
- `npm run lint` checks code style and common Next.js issues.
- `npm test` runs the test suite when configured.
- `npm run build` verifies the production build.

## Coding Style & Naming Conventions

Use TypeScript for application code. Prefer typed props, explicit return types for shared utilities, and narrow domain types for verification results. Use 2-space indentation for TypeScript, JSON, YAML, and Markdown. Name components in PascalCase, such as `VerificationResult.tsx`, and utility files in lowercase with hyphens, such as `risk-summary.ts`.

Use Phosphor Icons for interface icons via `@phosphor-icons/react/dist/ssr` so icons work in both server and client components. Prefer importing only the icons needed by each component, such as `import { ShieldCheck } from "@phosphor-icons/react/dist/ssr";`, and keep icon weights consistent with the surrounding UI.

Write product copy in clear Indonesian. Keep WaspadAI calm, credible, practical, and friendly.

## Testing Guidelines

Place tests under `tests/` or next to source files. Use names such as `verification.test.ts`, `chat.spec.tsx`, or `risk-summary.test.ts`. Cover core behavior, error paths, and changed workflows.

Document coverage expectations after a test runner is added.

## Commit & Pull Request Guidelines

There is no existing commit history, so use concise imperative commit messages, such as `Add authentication scaffold` or `Document repository setup`. Keep each commit focused on one logical change.

Pull requests should include a summary, testing notes, linked issues when applicable, and screenshots for UI changes. For UX or content changes, mention how the change supports: check, understand, decide.

## Product Guardrails

Keep the Verification use case central. Chat is the interface, not a general-purpose assistant. Results should make verdict, risk, reason, evidence, and recommended action easy to scan.

Do not fabricate evidence, sources, or certainty. Preserve uncertainty. Do not add out-of-scope concepts such as WhatsApp integration, background monitoring, Pelajari, Koneksi, admin dashboards, or account management unless requested.

## Technical Architecture References

Use `../../docs/frontend/context.md` for product and UX decisions. Use `../../docs/frontend/system-architecture.md` for the broader verification pipeline, `../../docs/frontend/rulebook-rag-architecture.md` for Rulebook RAG behavior, and `../../docs/integration.md` for the active API boundary. The FastAPI backend lives in `../api`; keep public claims aligned with features that are implemented and verified there.

## Security & Configuration Tips

Do not commit secrets, local credentials, or machine-specific configuration. Store examples in `.env.example` and document required variables in `docs/` or the README.

<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->
