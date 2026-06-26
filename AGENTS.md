# Repository Guidelines

## Project Structure

This is a **WeChat Mini Program** (微信小程序) — a card & board game center built on the WeChat cloud platform.

\\\
├── app.js / app.json / app.wxss    # App entry & config
├── cloudfunctions/getOpenId/       # Cloud function (WeChat login)
├── pages/                          # UI pages (one folder per game)
├── utils/                          # Core game logic & bot AI modules
├── agents/                         # Agent-specific instructions
└── project.config.json             # WeChat dev tools config
\\\

- **\pages/{game}/{game}.js/.wxml/.wxss/.json\** — Each game has its own page with UI, logic, and styling.
- **\utils/*.js\** — Shared game engines, evaluators, card decks, and bot AI (e.g., \card-game-base.js\, \hand-evaluator.js\, \ot-holdem.js\).
- **\cloudfunctions/\** — Serverless cloud functions (e.g., \getOpenId\ for WeChat user authentication).
- Supported games: Texas Hold'em, Omaha, Stud, Blackjack, Dou Di Zhu, Pao De Kuai, Guan Dan, Hearts, Riichi Mahjong, Wuhan Mahjong, Hangzhou Mahjong, UNO, Werewolf, Sanguosha.

## Build, Test, and Development

| Command / Tool | Description |
|---|---|
| **WeChat DevTools** | Open the project root in WeChat DevTools to preview, build, and upload. |
| **\project.config.json\** | Controls compilation settings (ES6, minification, cloud config). |
| **\cloudfunctions/\** | Right-click a function in DevTools to upload and deploy cloud functions. |

There is no npm-based build step; the WeChat DevTools handles all bundling and transpilation automatically.

## Coding Style & Naming Conventions

- **Indentation:** 2 spaces (configured in \project.config.json → editorSetting.tabSize: 2\).
- **Language:** ES6+ JavaScript (\es6: true\ in project config).
- **Naming:**
  - Files: \kebab-case.js\ (e.g., \card-game-base.js\, \ot-holdem.js\).
  - Folders: \snake_case\ (e.g., \hangzhou_mahjong\, \paodekuai\).
  - Variables/functions: \camelCase\ (e.g., \getOpenId\, \handlePlayerAction\).
- **Formatting:** PostCSS is enabled for WXSS; no JavaScript formatter is mandated — match the surrounding code style.
- **Game logic modules** export classes (e.g., \TexasGame\, \DouDiZhuGame\) that extend shared base classes from \utils/\.

## Testing Guidelines

- **No formal test framework** is currently in use. Game logic is tested via manual gameplay in the WeChat DevTools simulator or on-device.
- When adding or fixing logic, verify correctness by running the relevant game page in the DevTools simulator.
- Shared evaluator modules (e.g., \hand-evaluator.js\, \doudizhu-evaluator.js\) are good candidates for future unit tests.

## Commit & Pull Request Guidelines

- **Commit messages:** Write clear, imperative-style messages in English or Chinese describing what changed and why (e.g., \ix: correct hand ranking for straight flush\).
- **Pull requests:** Include a description of the change, any related game affected, and screenshots or simulator logs if visual behavior changed.
- Keep PRs focused — one game or one concern per pull request.

## Agent-Specific Instructions

The \CLAUDE.md\ file at the project root contains LLM behavioral guidelines (think before coding, simplicity first, surgical changes, goal-driven execution). This \AGENTS.md\ file follows the same scope rules — instructions here apply to all files within the \weixinxiaochengxu\ directory tree.
