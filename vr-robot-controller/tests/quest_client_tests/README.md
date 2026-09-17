# quest-client tests

The Quest-side page has no build step (plain HTML/JS + Three.js from a
CDN), so there's no bundler-based test runner set up yet. The highest-value
things to actually test here, if there's time:

- `input.js`'s `_extractYawDeg` quaternion math (pure function, easy to
  unit test with a small JS test runner like Vitest if one gets added)
- `network.js`'s reconnect/backoff behavior (harder — needs a mock
  WebSocket)

For now, these are covered by manual testing during the integration
milestone (see the roadmap in docs/architecture.md) rather than automated
tests — that's a reasonable trade-off given the project timeline, not an
oversight to fix later unless time allows.
