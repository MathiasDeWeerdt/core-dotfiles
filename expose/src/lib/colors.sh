# ── Colors (auto-detect terminal) ────────────────────────────────────────────
if [[ -t 2 ]]; then
  B=$'\e[1m' D=$'\e[2m' R=$'\e[0m' U=$'\e[4m'
  RED=$'\e[31m' GRN=$'\e[32m' YLW=$'\e[33m' BLU=$'\e[34m' CYN=$'\e[36m'
else
  B="" D="" R="" U="" RED="" GRN="" YLW="" BLU="" CYN=""
fi
