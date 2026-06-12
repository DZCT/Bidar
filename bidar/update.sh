#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════╗
# ║   Bidar — Safe Update Script                                     ║
# ║   به‌روزرسانی امن بدون از دست دادن session / .env / config         ║
# ║                                                                  ║
# ║   استفاده:                                                        ║
# ║     bash update.sh                                               ║
# ║   یا از راه دور (با توکن برای ریپو private):                        ║
# ║     export GH_TOKEN="ghp_..."                                    ║
# ║     bash <(curl -fsSL -H "Authorization: token $GH_TOKEN" \      ║
# ║       https://raw.githubusercontent.com/MamawliV2/Bidar/main/bidar/update.sh)  ║
# ╚══════════════════════════════════════════════════════════════════╝

set -euo pipefail

# ──────────────── پیکربندی ────────────────
REPO_URL="${BIDAR_REPO:-https://github.com/MamawliV2/Bidar.git}"
INSTALL_DIR="${BIDAR_DIR:-/opt/bidar}"
SERVICE_NAME="bidar"
EXTRA_INDEX="https://d33sy5i8bnduwe.cloudfront.net/simple/"

# فایل‌هایی که باید حفظ بشن (بکاپ شن)
PRESERVE_FILES=(
  ".env"
  "bidar_config.json"
  "bidar_session.session"
  "bidar_session.session-journal"
  "bidar.log"
  "bidar.out.log"
  "bidar.err.log"
)

# فایل‌هایی که آپدیت میشن (از ریپو کپی میشن)
UPDATE_FILES=(
  "bidar.py"
  "install.sh"
  "update.sh"
  "bidar.service"
  "requirements.txt"
  "README.md"
  "LICENSE"
  ".env.example"
  ".gitignore"
)

# ──────────────── رنگ‌ها ────────────────
if [[ -t 1 ]]; then
  C_RESET="\033[0m"; C_BOLD="\033[1m"
  C_BLUE="\033[34m"; C_GREEN="\033[32m"; C_YELLOW="\033[33m"
  C_RED="\033[31m"; C_CYAN="\033[36m"; C_MAGENTA="\033[35m"
else
  C_RESET=""; C_BOLD=""; C_BLUE=""; C_GREEN=""; C_YELLOW=""; C_RED=""; C_CYAN=""; C_MAGENTA=""
fi

say()   { echo -e "${C_CYAN}▸${C_RESET} $*"; }
ok()    { echo -e "${C_GREEN}✓${C_RESET} $*"; }
warn()  { echo -e "${C_YELLOW}⚠${C_RESET} $*"; }
err()   { echo -e "${C_RED}✗${C_RESET} $*" >&2; }
head1() { echo -e "\n${C_BOLD}${C_MAGENTA}━━ $* ━━${C_RESET}\n"; }

ask() {
  local prompt="$1" var="$2" default="${3:-}" secret="${4:-0}" allow_empty="${5:-0}" input=""
  local suffix=""
  [[ -n "$default" ]] && suffix=" ${C_YELLOW}[$default]${C_RESET}"
  [[ "$allow_empty" == "1" ]] && suffix+=" ${C_CYAN}(Enter برای رد)${C_RESET}"
  while true; do
    if [[ "$secret" == "1" ]]; then
      echo -en "${C_BLUE}?${C_RESET} ${prompt}${suffix}: " >&2
      IFS= read -rs input < /dev/tty || true
      echo "" >&2
    else
      echo -en "${C_BLUE}?${C_RESET} ${prompt}${suffix}: " >&2
      IFS= read -r input < /dev/tty || true
    fi
    input="${input:-$default}"
    if [[ -n "$input" ]] || [[ "$allow_empty" == "1" ]]; then
      printf -v "$var" '%s' "$input"
      return 0
    fi
    warn "این فیلد نمیتونه خالی باشه."
  done
}

ask_yes_no() {
  local prompt="$1" default="${2:-Y}" ans
  local hint="[Y/n]"; [[ "$default" =~ ^[Nn]$ ]] && hint="[y/N]"
  while true; do
    echo -en "${C_BLUE}?${C_RESET} ${prompt} ${C_YELLOW}${hint}${C_RESET}: " >&2
    IFS= read -r ans < /dev/tty || ans=""
    ans="${ans:-$default}"
    case "$ans" in
      [Yy]|[Yy][Ee][Ss]) return 0 ;;
      [Nn]|[Nn][Oo])     return 1 ;;
      *) warn "فقط y یا n بزن." ;;
    esac
  done
}

# ──────────────── sudo ────────────────
SUDO=""
if [[ $EUID -ne 0 ]]; then
  command -v sudo >/dev/null 2>&1 || { err "نیاز به root یا sudo"; exit 1; }
  SUDO="sudo"
fi

# ──────────────── بنر ────────────────
banner() {
  echo -e "${C_BOLD}${C_MAGENTA}"
  cat <<'EOF'

  ██████╗ ██╗██████╗  █████╗ ██████╗    ┬ ┬┌─┐┌┬┐┌─┐┌┬┐┌─┐
  ██╔══██╗██║██╔══██╗██╔══██╗██╔══██╗   │ │├─┘ ││├─┤ │ ├┤
  ██████╔╝██║██║  ██║███████║██████╔╝   └─┘┴  ─┴┘┴ ┴ ┴ └─┘
  ╚═════╝ ╚═╝╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝

  🔄  به‌روزرسانی امن
EOF
  echo -e "${C_RESET}"
}

# ──────────────── چک نصب ────────────────
check_install() {
  if [[ ! -f "${INSTALL_DIR}/bidar.py" ]]; then
    err "نصب Bidar در ${INSTALL_DIR} پیدا نشد."
    err "اول با install.sh نصب کن."
    exit 1
  fi
  ok "نصب قبلی پیدا شد در: ${INSTALL_DIR}"
}

# ──────────────── توقف سرویس ────────────────
stop_service() {
  head1 "توقف سرویس"
  if ! command -v systemctl >/dev/null 2>&1; then
    warn "systemd نیست — از این مرحله رد میشم"
    return 0
  fi
  if $SUDO systemctl is-active --quiet "${SERVICE_NAME}" 2>/dev/null; then
    say "توقف ${SERVICE_NAME}..."
    $SUDO systemctl stop "${SERVICE_NAME}"
    ok "متوقف شد"
  else
    say "سرویس اجرا نبود"
  fi
}

# ──────────────── بکاپ ────────────────
BACKUP_DIR=""
backup_files() {
  head1 "بکاپ فایل‌های مهم"
  BACKUP_DIR="$(mktemp -d -t bidar-backup-XXXXX)"
  say "مسیر بکاپ: ${BACKUP_DIR}"
  for f in "${PRESERVE_FILES[@]}"; do
    if [[ -f "${INSTALL_DIR}/${f}" ]]; then
      cp -p "${INSTALL_DIR}/${f}" "${BACKUP_DIR}/"
      say "  ✓ ${f}"
    fi
  done
  ok "بکاپ تمام شد"
}

restore_files() {
  say "برگردوندن فایل‌ها از بکاپ..."
  for f in "${PRESERVE_FILES[@]}"; do
    if [[ -f "${BACKUP_DIR}/${f}" ]]; then
      $SUDO cp -p "${BACKUP_DIR}/${f}" "${INSTALL_DIR}/${f}"
    fi
  done
  ok "بازگردانی انجام شد"
}

# ──────────────── کلون سورس جدید ────────────────
TMP_DIR=""
fetch_new_source() {
  head1 "دریافت سورس جدید"
  TMP_DIR="$(mktemp -d -t bidar-update-XXXXX)/src"
  mkdir -p "$TMP_DIR"

  local clone_url="${REPO_URL}"
  if [[ -n "${GH_TOKEN:-}${GITHUB_TOKEN:-}" ]]; then
    local token="${GH_TOKEN:-${GITHUB_TOKEN}}"
    clone_url="${REPO_URL/https:\/\//https://oauth2:${token}@}"
    say "🔑 استفاده از توکن برای ریپو private"
  fi

  if ! git clone --depth 1 "$clone_url" "$TMP_DIR" 2>&1 | \
       sed "s/${GH_TOKEN:-NOTSET}/***/g; s/${GITHUB_TOKEN:-NOTSET}/***/g"; then
    err "کلون ناموفق!"
    exit 1
  fi

  # تشخیص محل فایل‌ها
  if [[ -f "$TMP_DIR/bidar.py" ]]; then
    SRC_DIR="$TMP_DIR"
  elif [[ -f "$TMP_DIR/bidar/bidar.py" ]]; then
    SRC_DIR="$TMP_DIR/bidar"
  else
    err "bidar.py در ریپو پیدا نشد"
    exit 1
  fi
  ok "سورس جدید آماده است"
}

# ──────────────── آپدیت فایل‌ها ────────────────
apply_updates() {
  head1 "اعمال تغییرات"
  local updated=0
  for f in "${UPDATE_FILES[@]}"; do
    if [[ -f "${SRC_DIR}/${f}" ]]; then
      if [[ -f "${INSTALL_DIR}/${f}" ]] && cmp -s "${SRC_DIR}/${f}" "${INSTALL_DIR}/${f}"; then
        :  # بدون تغییر
      else
        $SUDO cp -p "${SRC_DIR}/${f}" "${INSTALL_DIR}/${f}"
        say "  ✓ ${f}"
        updated=$((updated + 1))
      fi
    fi
  done
  ok "${updated} فایل آپدیت شد"
}

# ──────────────── بررسی متغیرهای جدید ────────────────
check_new_env_vars() {
  head1 "بررسی متغیرهای .env"

  # EMERGENT_LLM_KEY (جدید در v1.3.0)
  if ! grep -q "^EMERGENT_LLM_KEY=" "${INSTALL_DIR}/.env"; then
    warn "متغیر جدید EMERGENT_LLM_KEY در .env نیست."
    echo ""
    echo -e "${C_BOLD}🧠 دستیار هوش مصنوعی در این نسخه اضافه شده.${C_RESET}"
    echo "   کلیدت رو از پروفایل Emergent → Universal Key بگیر."
    echo ""
    local KEY=""
    if ask_yes_no "میخوای EMERGENT_LLM_KEY رو الان اضافه کنی؟" "Y"; then
      ask "EMERGENT_LLM_KEY" KEY "" 1 1
    fi
    local tmp
    tmp=$(mktemp)
    {
      echo ""
      echo "# ─── AI Assistant (Emergent Universal Key) ───"
      echo "EMERGENT_LLM_KEY=${KEY}"
    } >> "$tmp"
    $SUDO tee -a "${INSTALL_DIR}/.env" < "$tmp" >/dev/null
    rm "$tmp"
    $SUDO chmod 600 "${INSTALL_DIR}/.env"
    if [[ -n "$KEY" ]]; then
      ok "کلید ذخیره شد"
    else
      warn "کلید خالی ذخیره شد — AI فعلاً غیرفعاله. بعداً با nano .env اضافه کن."
    fi
  else
    ok "EMERGENT_LLM_KEY از قبل در .env هست"
  fi
}

# ──────────────── نصب پکیج‌های جدید ────────────────
update_deps() {
  head1 "به‌روزرسانی وابستگی‌های پایتون"
  if [[ ! -f "${INSTALL_DIR}/venv/bin/pip" ]]; then
    warn "venv پیدا نشد — ساخته میشه"
    $SUDO python3 -m venv "${INSTALL_DIR}/venv"
  fi
  say "نصب/به‌روزرسانی پکیج‌ها..."
  $SUDO "${INSTALL_DIR}/venv/bin/pip" install --upgrade pip >/dev/null
  $SUDO "${INSTALL_DIR}/venv/bin/pip" install -r "${INSTALL_DIR}/requirements.txt" \
    --extra-index-url "${EXTRA_INDEX}"
  ok "وابستگی‌ها به‌روز شدن"
}

# ──────────────── نصب ffmpeg (برای MP3 ساندکلاد) ────────────────
ensure_ffmpeg() {
  head1 "بررسی ffmpeg (برای دانلود موزیک ساندکلاد)"
  if command -v ffmpeg >/dev/null 2>&1; then
    ok "ffmpeg نصبه"
    return 0
  fi
  warn "ffmpeg نصب نیست — برای خروجی MP3 با کیفیت در دستور .sc توصیه میشه."
  if command -v apt-get >/dev/null 2>&1; then
    $SUDO apt-get update -y >/dev/null 2>&1 || true
    $SUDO DEBIAN_FRONTEND=noninteractive apt-get install -y ffmpeg || warn "نصب ffmpeg ناموفق بود (اختیاریه)"
  elif command -v dnf >/dev/null 2>&1; then
    $SUDO dnf install -y ffmpeg || warn "نصب ffmpeg ناموفق بود (اختیاریه)"
  elif command -v yum >/dev/null 2>&1; then
    $SUDO yum install -y ffmpeg || warn "نصب ffmpeg ناموفق بود (اختیاریه)"
  elif command -v pacman >/dev/null 2>&1; then
    $SUDO pacman -Sy --noconfirm ffmpeg || warn "نصب ffmpeg ناموفق بود (اختیاریه)"
  elif command -v apk >/dev/null 2>&1; then
    $SUDO apk add --no-cache ffmpeg || warn "نصب ffmpeg ناموفق بود (اختیاریه)"
  else
    warn "پکیج منیجر ناشناخته — ffmpeg رو دستی نصب کن"
  fi
}

# ──────────────── آپدیت سرویس systemd ────────────────
update_service() {
  local svc_file="/etc/systemd/system/${SERVICE_NAME}.service"
  [[ ! -f "$svc_file" ]] && return 0
  [[ ! -f "${INSTALL_DIR}/bidar.service" ]] && return 0

  local user
  user=$(grep -oP '^User=\K.*' "$svc_file" 2>/dev/null || echo "root")
  local tmp
  tmp=$(mktemp)
  sed -e "s|__INSTALL_DIR__|${INSTALL_DIR}|g" \
      -e "s|__SERVICE_USER__|${user}|g" \
      "${INSTALL_DIR}/bidar.service" > "$tmp"
  if ! cmp -s "$tmp" "$svc_file"; then
    $SUDO cp "$tmp" "$svc_file"
    $SUDO systemctl daemon-reload
    say "فایل سرویس systemd آپدیت شد"
  fi
  rm "$tmp"
}

# ──────────────── شروع سرویس ────────────────
start_service() {
  head1 "شروع مجدد سرویس"
  if ! command -v systemctl >/dev/null 2>&1; then
    warn "systemd نیست — دستی اجرا کن: ${INSTALL_DIR}/venv/bin/python ${INSTALL_DIR}/bidar.py"
    return 0
  fi
  $SUDO systemctl start "${SERVICE_NAME}"
  sleep 3
  if $SUDO systemctl is-active --quiet "${SERVICE_NAME}"; then
    ok "سرویس ${SERVICE_NAME} فعال شد 🟢"
  else
    err "سرویس بالا نیومد!"
    err "لاگ رو چک کن:"
    err "  journalctl -u ${SERVICE_NAME} -n 50 --no-pager"
    err "  tail -50 ${INSTALL_DIR}/bidar.err.log"
    err ""
    err "برای برگردوندن بکاپ دستی:"
    err "  sudo cp ${BACKUP_DIR}/* ${INSTALL_DIR}/"
    exit 1
  fi
}

# ──────────────── پاک‌سازی ────────────────
cleanup() {
  [[ -n "${TMP_DIR:-}" ]] && rm -rf "$(dirname "$TMP_DIR")"
}
trap cleanup EXIT

# ──────────────── پایان ────────────────
farewell() {
  head1 "به‌روزرسانی با موفقیت تمام شد 🎉"
  cat <<EOF
🎯 چند قدم بعدی:
   ${C_CYAN}systemctl status ${SERVICE_NAME}${C_RESET}     # وضعیت سرویس
   ${C_CYAN}journalctl -u ${SERVICE_NAME} -f${C_RESET}    # لاگ زنده

💾 بکاپ در: ${BACKUP_DIR}
   (در صورت مشکل: sudo cp ${BACKUP_DIR}/* ${INSTALL_DIR}/)

🧠 اگه EMERGENT_LLM_KEY خالی گذاشتی، بعد از ادیت .env:
   ${C_CYAN}sudo nano ${INSTALL_DIR}/.env${C_RESET}
   ${C_CYAN}sudo systemctl restart ${SERVICE_NAME}${C_RESET}

📱 توی تلگرامت تایپ کن: .help  یا  .stats
   برای فعال کردن AI: .ai on

EOF
}

# ──────────────── اجرا ────────────────
main() {
  banner
  check_install
  stop_service
  backup_files
  fetch_new_source
  apply_updates
  restore_files         # دوباره برمی‌گردیم تا مطمئن بشیم session/env حفظ شدن
  check_new_env_vars
  update_deps
  ensure_ffmpeg
  update_service
  start_service
  farewell
}

main "$@"
