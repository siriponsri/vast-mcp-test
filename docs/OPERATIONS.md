# Runbook: one on-demand instance, owner-controlled

## Gate before any T3 credential

Use the Console or offline fixtures while the grant is unverified. Default keys are full access, and blanket `misc` includes changes to serverless resources. A successful Search Offers request confirms search access only. [Search-key gate](VAST_SEARCH_KEY.md)

## Before opening a paid prompt

1. Check available funds, prior open instances, no stored account-level environment secrets, and SSH public key configured in the right Vast account. Use a clean identity or explicitly clear infrastructure safety separately. Do not put secrets in the container, AI session, repo, or copied logs.
2. Run only an authorized request with public/synthetic inputs. Counts: 1 GPU, 1 on-demand instance, disk 8–100 GB, planned time 1–120 min, maximum configurable listed rate $2/hour and maximum configurable planning estimate $8; pick lower limits for smoke. The search quote uses `allocated_storage` equal to create `disk`. Estimate uses `dph_total × planned minutes ÷ 60`; `dph_total` includes quoted GPU and disk, counted once. Bandwidth, fees, taxes and actual runtime may change the bill. These are software limits, not budget authorization or guaranteed ceilings.
3. With Vast Console available, set a personal timer earlier than the approved teardown deadline. Ensure bandwidth charges and any required minimum credit are acceptable. The starter does not add credit or make hosting/storage changes.
4. Verify typed confirmation: `RENT <offer-id> <first-16-of-quote-sha>`. A fresh exact marketplace lookup with the same constraints must still produce the same decision fields. A price rise even under the original cap aborts. Quote expires after 90 seconds; no implicit approval of another offer. For safety no auto-create retries are attempted.

## Operational proof

- After create, provider acknowledgment gives an ID, not live GPU. Check `status` and compare `live_rate_check`; unknown rate is not verification. If the provider reports a higher rate, do not connect; inspect and stop/destroy.
- On `running`, use `connection`. It only displays allowlisted SSH parameters, does not execute. Supported host hints are Vast SSH proxy and globally routed IPv4 with a valid port. If provider returns another format, rely on the matching instance's **Connect** panel / official `vastai ssh-url` rather than weakening validation. If the platform does not return a trustworthy host key, do not connect until independently verified.
- Manually check `nvidia-smi -L`; record observed GPU model, timestamp and exit code only. A smoke test should not run a real PTP experiment. If subsequently authorized to use the GPU for a workload, stage only approved data, explicitly prepare dependencies after access, and retain output outside the instance.
- Stop uses owner-confirmed `STOP <instance-id>`; in the listed state `stopped` or `exited` only GPU compute cessation is evidenced. Storage can continue billing. Destroy uses `DESTROY <instance-id>`; first save and verify data you intend to keep. Cleanup verifies acknowledged destroy, exact ID 404, and a complete authenticated listing with neither exact ID nor unique label. If any signal is missing mark cleanup unverified and inspect Console; 404 alone is not proof. Pending state remains visible.

## Reconcile ambiguous outcomes

- `receipt` is local only. It returns the full unique label `ptp-vast-...`; use that exact label and same Vast account while resolving ambiguity. Never retry rent on timeout, browser disconnect, or malformed response.
- `reconcile` for create traverses up to 10 complete listing pages and adopts only one exact label with a successful exact-ID ownership check. If listing is incomplete, no match, or ambiguous, keep the local pending lease; use Console and do not rent again. If Console shows the single exact label, `adopt ID` also verifies exact ID/label before recording it.
- If stop/destroy timed out, inspect the receipt and Console. A pending or acknowledged operation may still be running. Do not send another operation blindly, don't delete unrelated instances, and don't clear the ledger yourself to suppress warnings. This starter intentionally lacks a force-reset command; uncertain records require manual operator/provider reconciliation before a new independent task.
- Even after cleanup, check the provider billing/instance views for settled status and any actual spend. No automatic watchdog/TTL, no provider-side spend limit, and no recovery after compromised credentials; responsibility for ongoing costs stays with the human operator.

## API sources

- [Search Offers](https://docs.vast.ai/api-reference/search/search-offers): `POST /api/v0/bundles` is read-only search, not renting.
- [Create Instance](https://docs.vast.ai/api-reference/instances/create-instance), [Show Instance](https://docs.vast.ai/api-reference/instances/show-instance), [Show Instances](https://docs.vast.ai/api-reference/instances/show-instances), [Manage Instance](https://docs.vast.ai/api-reference/instances/manage-instance), [Destroy Instance](https://docs.vast.ai/api-reference/instances/destroy-instance).
- [SSH URL](https://docs.vast.ai/cli/reference/ssh-url), [Pricing](https://docs.vast.ai/guides/pricing), [Vast official tool guidance](https://github.com/vast-ai/vast-codex-plugin/blob/main/skills/vastai/SKILL.md).
