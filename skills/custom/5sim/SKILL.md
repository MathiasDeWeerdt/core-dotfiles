---
name: 5sim
description: Compare 5SIM activation prices and stock, preview a purchase, or manage a single SMS order for a service the user requests. Use to find a product, wait for an expected SMS, and finish or cancel the order.
---

# 5SIM

Use the bundled `scripts/5simctl`. It requires Bash, curl, jq and flock on Linux. After installation, set:

```sh
sim="$HOME/.agents/skills/5sim/scripts/5simctl"
```

## Find an offer

```sh
"$sim" search "$service"
"$sim" prices "$product" --limit 10
"$sim" cheapest "$product"
```

These commands use the public catalog. Select the product for the requested service. Use `other` only for an unlisted service that accepts it. Prices and stock change. Start with the cheapest available offer for that product. Apply `--country` if the user or service requires one. Use `--min-rate` for a requested delivery-rate threshold. A missing rate appears as zero. `cheapest-any` compares offers across products.

## Buy and settle one order

Buy only when the user requests a paid number for the specified service. Use the user's price limit when provided. The preview checks the balance and current offers without placing an order.

```sh
"$sim" buy "$product" --max-price "$cap" --dry-run
"$sim" buy "$product" --max-price "$cap"
"$sim" wait "$id" --code-only
```

Keep the order ID returned by `buy`. An explicit price cap takes precedence over the account's product price setting. With a cap, 5SIM chooses the operator in the selected country. A specific operator or its delivery rate cannot be guaranteed with a server-enforced cap. Without a cap the helper requests the selected operator at the current price. [5SIM API documentation](https://5sim.net/docs#buy-activation-number)

Use the SMS only for the requested verification. Keep the number, message and code out of logs and reports. After the code works, run `"$sim" finish "$id"`. If the wait expires, use `check "$id"` to see whether a message arrived. Use `cancel "$id"` for an unused order, or `ban "$id"` to report an unusable number when appropriate. Check the returned status. The provider determines any refund.

If a purchase times out or the result is unclear, run `orders` before taking further action. Keep one open activation at a time. The helper allows three purchase attempts per product in 24 hours, at least two minutes apart. Inspect `attempts --product "$product"` after a failure. Use `--force` to override these two attempt limits only with explicit user approval. It still checks for an open order.

## Private setup

Store the 5SIM v1 token in `~/.config/core-dotfiles/5sim/token` with mode `0600`. Public catalog commands work without a token. `balance`, order commands and purchase previews require one.

The helper respects `XDG_CONFIG_HOME` and also accepts an existing `5sim/token` there when the new file is absent. Set `FIVESIM_TOKEN_FILE` to choose another private file. Attempts stay under `$XDG_STATE_HOME/5sim` (default `~/.local/state/5sim`). Keep state and credentials outside Git. Run `"$sim" help` for all commands.
