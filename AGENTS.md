Use independent Python 3.11 in the project .venv. Product dependencies must not include Codex, LLMs, private desktop runtimes, or game resources.
Default to replay/dry-run. Native input is restricted to the independently launched MTGAPlayer harness, with PID/HWND/nonce and screenshot identity checks. Never send input to MTGA without explicit scope authorization.
Unknown, expired, discontinuous, conflicting, stopped or unsupported state must block input. Keep diagnostic last_valid separate from actionable current.
Run `python -m unittest discover -s tests -v`; Windows read-only probe: `mtgaplayer doctor`. Native evidence requires actual screenshots/SendInput and semantic postconditions; replay cannot establish it.
Maintain temporary status only in docs/progress.md. Review task requirements, diff, code and raw evidence independently. Do not equate harness support with MTGA support or basic tactics with optimal play.
