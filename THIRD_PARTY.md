# Third-party provenance and notices

This repository includes maintained adaptations of the following material.
Upstream copyright, license texts, and asset notices remain with their files.
The repository's own notices do not replace those terms or claim ownership of
third-party material. Inclusion does not imply upstream endorsement.

| Location | Provenance | Retained notices |
| --- | --- | --- |
| `third_party/cc-skills-golang` | [samber/cc-skills-golang](https://github.com/samber/cc-skills-golang), by Samuel Berthe; maintained entrypoints, references, and tooling | `LICENSE` (MIT) |
| `third_party/db-postgres` | [`db-postgres` in ScotterMonk/AgentAutoFlow](https://github.com/ScotterMonk/AgentAutoFlow/tree/main/.kilocode/skills/db-postgres); the skill credits [Jeffallan](https://github.com/Jeffallan) and records upstream version 1.1.0 | The skill declares MIT; the retained source-repository `LICENSE` is CC0 1.0. Both statements are retained; no single license is asserted for the whole directory. |
| `third_party/drawio-skill` | [Agents365-ai/drawio-skill](https://github.com/Agents365-ai/drawio-skill), recorded skill version 1.28.0; maintained entrypoint and export guidance | `LICENSE` (MIT), upstream Git blob `ec170ad92004bdbdab67fd639a3104a97722373d`; retained shape and asset notices |
| `third_party/typesafe-ai` | [typesafe-ai/skills](https://github.com/typesafe-ai/skills/tree/main/skills/typesafe-ai); [official documentation](https://docs.typesafe.ai/) | `LICENSE` (MIT, copyright TypeSafe AI); the vendored distribution contains `SKILL.md`, `references/development-consultations.md`, and `LICENSE` |
| `skills/security-threat-model` | Locally maintained adaptation with retained reference material; no upstream revision is asserted | `LICENSE.txt` (Apache-2.0) |

The security threat-model adaptation narrows its trigger, updates the invocation
prompt, and asks for clarification only when missing context materially affects
the requested result. The PostgreSQL and Draw.io adaptations resolve resources
relative to the installed skill and apply task-scoped evidence and completion
guidance. TypeSafe consultation guidance is retained with its vendored skill.

The Go testing adaptation adds an optional catalog-resolved route to this suite's
original `test-strategy` Go fuzzing reference, with a source-relative fallback.
The reference is first-party guidance; it does not replace upstream Go testing
resources or their MIT notice. TypeSafe's discovery description is shortened
locally without upgrading or changing its API/integration guidance. These are
maintained adaptations of the retained material, not new upstream revisions.

Draw.io's supplied shape documentation includes notices for upstream icon sets;
consult those notices before reusing or redistributing their assets. The skill
license does not replace asset-specific terms.

The native installer links these pinned Go dependencies; their notices are also
bundled with release archives:

| Module | Version | Retained license |
| --- | --- | --- |
| [Go runtime and standard library](https://github.com/golang/go/tree/go1.27.1) | go1.27.1 | [BSD notice](licenses/go-LICENSE) |
| [pelletier/go-toml](https://github.com/pelletier/go-toml) | v2.2.3 | [MIT notice](licenses/go-toml-LICENSE) |
| [go-yaml/yaml](https://github.com/go-yaml/yaml) | v3.0.1 | [MIT/Apache notices](licenses/yaml-LICENSE) |
| [spf13/cobra](https://github.com/spf13/cobra) | v1.10.2 | [Apache notice](licenses/cobra-LICENSE) |
| [spf13/pflag](https://github.com/spf13/pflag) | v1.0.9 | [BSD notice](licenses/pflag-LICENSE) |
| [inconshreveable/mousetrap](https://github.com/inconshreveable/mousetrap) | v1.1.0 | [Apache notice](licenses/mousetrap-LICENSE) |
