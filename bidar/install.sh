#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════╗
# ║                                                                  ║
# ║   Bidar — Always Online Telegram Userbot                         ║
# ║   نصاب خودکار (پیش‌نیازها + پیکربندی + سرویس سیستمی)              ║
# ║                                                                  ║
# ║   استفاده:                                                        ║
# ║     bash <(curl -fsSL <RAW_URL>)                                 ║
# ║   یا (بعد از کلون):                                                ║
# ║     bash install.sh                                              ║
# ║                                                                  ║
# ╚══════════════════════════════════════════════════════════════════╝

set -euo pipefail

# ──────────────── پیکربندی پیش‌فرض ────────────────
REPO_URL="${BIDAR_REPO:-https://github.com/DZCT/Bidar.git}"
INSTALL_DIR="${BIDAR_DIR:-/opt/bidar}"
SERVICE_NAME="bidar"
PYTHON_MIN="3.10"

# ──────────────── رنگ‌ها (ANSI) ────────────────
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

# ──────────────── ورودی تعاملی امن (حتی وقتی با pipe اجرا بشه) ────────────────
ask() {
  # $1=prompt, $2=var_name, $3=default(optional), $4=secret(0/1), $5=allow_empty(0/1)
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
  # $1=prompt, $2=default(Y/n), returns 0=yes 1=no
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

# ──────────────── بنر ────────────────
banner() {
  echo -e "${C_BOLD}${C_MAGENTA}"
  cat <<'EOF'

  ██████╗ ██╗██████╗  █████╗ ██████╗
  ██╔══██╗██║██╔══██╗██╔══██╗██╔══██╗
  ██████╔╝██║██║  ██║███████║██████╔╝
  ██╔══██╗██║██║  ██║██╔══██║██╔══██╗
  ██████╔╝██║██████╔╝██║  ██║██║  ██║
  ╚═════╝ ╚═╝╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝

  🌙  Always-Online Telegram Userbot
EOF
  echo -e "${C_RESET}"
}

# ──────────────── ریشه / sudo ────────────────
SUDO=""
if [[ $EUID -ne 0 ]]; then
  if command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
  else
    err "این اسکریپت نیاز به دسترسی root داره (یا sudo نصب باشه)."
    exit 1
  fi
fi

# ──────────────── شناسایی پکیج منیجر ────────────────
detect_pm() {
  if command -v apt-get >/dev/null 2>&1; then echo "apt"
  elif command -v dnf     >/dev/null 2>&1; then echo "dnf"
  elif command -v yum     >/dev/null 2>&1; then echo "yum"
  elif command -v pacman  >/dev/null 2>&1; then echo "pacman"
  elif command -v apk     >/dev/null 2>&1; then echo "apk"
  else echo "unknown"; fi
}

pm_install() {
  local pm="$1"; shift
  say "نصب پکیج‌ها: $*"
  case "$pm" in
    apt)    $SUDO apt-get update -y >/dev/null 2>&1 || true
            $SUDO DEBIAN_FRONTEND=noninteractive apt-get install -y "$@" ;;
    dnf)    $SUDO dnf install -y "$@" ;;
    yum)    $SUDO yum install -y "$@" ;;
    pacman) $SUDO pacman -Sy --noconfirm "$@" ;;
    apk)    $SUDO apk add --no-cache "$@" ;;
    *)      err "پکیج منیجر شناخته نشد؛ لطفاً دستی نصب کن: $*"; exit 1 ;;
  esac
}

# ──────────────── چک و نصب پیش‌نیازها ────────────────
ensure_prereqs() {
  head1 "بررسی پیش‌نیازها"
  local pm; pm=$(detect_pm)
  say "پکیج منیجر: ${C_BOLD}$pm${C_RESET}"

  local need=()
  command -v python3 >/dev/null 2>&1 || need+=(python3)
  command -v pip3    >/dev/null 2>&1 || need+=(python3-pip)
  python3 -c "import venv" 2>/dev/null || need+=(python3-venv)
  command -v git     >/dev/null 2>&1 || need+=(git)
  command -v curl    >/dev/null 2>&1 || need+=(curl)
  command -v ffmpeg  >/dev/null 2>&1 || need+=(ffmpeg)

  # اصلاح اسامی برای پکیج منیجرهای non-debian
  if [[ "$pm" != "apt" ]]; then
    local alt=()
    for p in "${need[@]}"; do
      case "$p" in
        python3-pip|python3-venv) alt+=(python3) ;;
        *) alt+=("$p") ;;
      esac
    done
    need=("${alt[@]}")
  fi

  if [[ ${#need[@]} -gt 0 ]]; then
    # حذف تکراری
    local uniq=(); declare -A seen=()
    for p in "${need[@]}"; do [[ -z "${seen[$p]:-}" ]] && { uniq+=("$p"); seen[$p]=1; }; done
    warn "این پکیج‌ها نصب نیستن: ${uniq[*]}"
    pm_install "$pm" "${uniq[@]}" || warn "نصب بعضی پکیج‌ها ناموفق بود (ffmpeg اختیاریه — برای خروجی MP3 دانلود ساندکلاد)"
  fi

  # چک ورژن پایتون
  local pyv
  pyv=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
  if ! python3 -c "import sys; assert sys.version_info >= (3,10)" 2>/dev/null; then
    err "پایتون $pyv شناسایی شد؛ حداقل ${PYTHON_MIN} لازمه."
    exit 1
  fi
  ok "پایتون $pyv ✓"
  ok "همه پیش‌نیازها آماده شدن."
}

# ──────────────── کپی/کلون پروژه ────────────────
fetch_project() {
  head1 "دریافت سورس Bidar"
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd 2>/dev/null || pwd)"

  # اگه از داخل مسیر پروژه اجرا شده
  if [[ -f "${script_dir}/bidar.py" ]]; then
    say "پروژه محلی پیدا شد: ${script_dir}"
    if [[ "${script_dir}" == "${INSTALL_DIR}" ]]; then
      ok "همین مسیر استفاده میشه."
    else
      say "کپی به ${INSTALL_DIR}"
      $SUDO mkdir -p "${INSTALL_DIR}"
      $SUDO cp -r "${script_dir}/." "${INSTALL_DIR}/"
    fi
  else
    say "کلون از: ${REPO_URL}"
    local tmp_dir="/tmp/bidar-clone-$$"
    rm -rf "$tmp_dir"

    # اگه توکن گیت‌هاب تنظیم شده (برای ریپو private)
    local clone_url="${REPO_URL}"
    if [[ -n "${GH_TOKEN:-}${GITHUB_TOKEN:-}" ]]; then
      local token="${GH_TOKEN:-${GITHUB_TOKEN}}"
      clone_url="${REPO_URL/https:\/\//https://oauth2:${token}@}"
      say "🔑 از توکن گیت‌هاب برای دسترسی استفاده میشه"
    fi

    if ! $SUDO git clone --depth 1 "$clone_url" "$tmp_dir" 2>&1 | sed "s/${GH_TOKEN:-NOTSET}/***/g; s/${GITHUB_TOKEN:-NOTSET}/***/g"; then
      err "کلون ناموفق. اگه ریپو private هست، مطمئن شو GH_TOKEN تنظیم شده."
      rm -rf "$tmp_dir"
      exit 1
    fi

    # تشخیص محل فایل‌ها: ریشه ریپو یا داخل bidar/ subfolder
    local source_dir=""
    if [[ -f "$tmp_dir/bidar.py" ]]; then
      source_dir="$tmp_dir"
      say "فایل‌ها در ریشه ریپو پیدا شدن."
    elif [[ -f "$tmp_dir/bidar/bidar.py" ]]; then
      source_dir="$tmp_dir/bidar"
      say "فایل‌ها در subfolder bidar/ پیدا شدن."
    else
      err "bidar.py در ریپو پیدا نشد! ساختار ریپو رو چک کن."
      rm -rf "$tmp_dir"
      exit 1
    fi

    $SUDO mkdir -p "${INSTALL_DIR}"
    $SUDO cp -r "$source_dir/." "${INSTALL_DIR}/"
    rm -rf "$tmp_dir"
  fi
  ok "سورس در ${INSTALL_DIR} قرار گرفت."
}

# ──────────────── venv + pip install ────────────────
setup_venv() {
  head1 "ساخت محیط مجازی پایتون"
  $SUDO python3 -m venv "${INSTALL_DIR}/venv"
  $SUDO "${INSTALL_DIR}/venv/bin/pip" install --upgrade pip >/dev/null
  # emergentintegrations از index خاص خودش نصب میشه
  $SUDO "${INSTALL_DIR}/venv/bin/pip" install -r "${INSTALL_DIR}/requirements.txt" \
    --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/
  ok "venv ساخته شد و پکیج‌ها نصب شدن."
}

# ──────────────── گرفتن مقادیر از کاربر و ساخت .env ────────────────
prompt_env() {
  head1 "تنظیمات تلگرام"
  if [[ -f "${INSTALL_DIR}/.env" ]]; then
    warn "فایل .env موجوده."
    if ! ask_yes_no "میخوای جایگزین بشه؟" "n"; then
      ok "از .env فعلی استفاده میشه."
      return 0
    fi
  fi

  echo -e "${C_BOLD}📌 اگه هنوز نگرفتی، API_ID و API_HASH رو از اینجا بگیر:${C_RESET}"
  echo -e "   ${C_CYAN}https://my.telegram.org/apps${C_RESET}\n"

  local API_ID API_HASH PHONE AFK_MSG AFK_CD EMERGENT_KEY=""
  ask "API_ID (عدد)"                                   API_ID
  ask "API_HASH"                                       API_HASH "" 1
  ask "شماره موبایل (با کد کشور، مثل +989121234567)"    PHONE
  ask "متن پیش‌فرض AFK"                                AFK_MSG \
      "سلام 👋 الان در دسترس نیستم، پیامت رو دیدم و به زودی پاسخ میدم 🙏"
  ask "Cooldown پاسخ AFK به هر نفر (ثانیه)"            AFK_CD "1800"

  echo ""
  echo -e "${C_BOLD}🧠 دستیار هوش مصنوعی (اختیاری):${C_RESET}"
  echo -e "   ${C_CYAN}از پروفایل Emergent → Universal Key کلیدت رو کپی کن${C_RESET}"
  if ask_yes_no "می‌خوای دستیار AI رو فعال کنی؟" "Y"; then
    ask "EMERGENT_LLM_KEY" EMERGENT_KEY "" 1 1
  fi

  local tmp; tmp=$(mktemp)
  cat > "$tmp" <<EOF
# ─── Bidar Configuration ───
API_ID=${API_ID}
API_HASH=${API_HASH}
PHONE=${PHONE}
SESSION_NAME=bidar_session
AFK_MESSAGE=${AFK_MSG}
AFK_COOLDOWN=${AFK_CD}
CMD_PREFIX=.

# ─── AI Assistant (Emergent Universal Key) ───
EMERGENT_LLM_KEY=${EMERGENT_KEY}
EOF
  $SUDO mv "$tmp" "${INSTALL_DIR}/.env"
  $SUDO chmod 600 "${INSTALL_DIR}/.env"
  ok ".env ساخته شد (${INSTALL_DIR}/.env)"
}

# ──────────────── لاگین اولیه (گرفتن کد SMS) ────────────────
first_login() {
  head1 "لاگین اولیه به تلگرام"
  say "تلگرام یه کد تایید برات میفرسته. وارد کن، بعد اگه 2FA داری پسوردت رو."
  say "بعد از موفقیت، Ctrl+C بزن تا بره سراغ مرحله بعد.\n"
  if ! ask_yes_no "الان لاگین اولیه رو انجام بدم؟" "Y"; then
    warn "باشه؛ بعداً خودت اجرا کن:  ${INSTALL_DIR}/venv/bin/python ${INSTALL_DIR}/bidar.py"
    return 0
  fi
  $SUDO "${INSTALL_DIR}/venv/bin/python" "${INSTALL_DIR}/bidar.py" || true
  ok "لاگین اولیه تموم شد."
}

# ──────────────── نصب سرویس systemd ────────────────
install_service() {
  head1 "نصب سرویس systemd"
  if ! command -v systemctl >/dev/null 2>&1; then
    warn "systemd روی این سیستم نیست — از این مرحله رد میشم."
    return 0
  fi
  if ! ask_yes_no "Bidar رو به عنوان سرویس همیشه‌روشن نصب کنم؟" "Y"; then
    ok "سرویس نصب نشد. برای اجرای دستی:  ${INSTALL_DIR}/venv/bin/python ${INSTALL_DIR}/bidar.py"
    return 0
  fi
  local SERVICE_USER="${SUDO_USER:-root}"
  local tmp; tmp=$(mktemp)
  sed -e "s|__INSTALL_DIR__|${INSTALL_DIR}|g" \
      -e "s|__SERVICE_USER__|${SERVICE_USER}|g" \
      "${INSTALL_DIR}/bidar.service" > "$tmp"
  $SUDO mv "$tmp" "/etc/systemd/system/${SERVICE_NAME}.service"
  $SUDO systemctl daemon-reload
  $SUDO systemctl enable "${SERVICE_NAME}" >/dev/null
  $SUDO systemctl restart "${SERVICE_NAME}"
  sleep 2
  if $SUDO systemctl is-active --quiet "${SERVICE_NAME}"; then
    ok "سرویس ${SERVICE_NAME} فعال شد."
  else
    err "سرویس بالا نیومد. لاگ:  journalctl -u ${SERVICE_NAME} -n 50 --no-pager"
  fi
}

# ──────────────── پایان ────────────────
farewell() {
  head1 "تمام شد 🎉"
  cat <<EOF
📁 مسیر نصب: ${INSTALL_DIR}
🔧 دستورات مفید:

   ${C_CYAN}systemctl status ${SERVICE_NAME}${C_RESET}      # وضعیت سرویس
   ${C_CYAN}journalctl -u ${SERVICE_NAME} -f${C_RESET}     # لاگ زنده
   ${C_CYAN}systemctl restart ${SERVICE_NAME}${C_RESET}    # ری‌استارت
   ${C_CYAN}tail -f ${INSTALL_DIR}/bidar.log${C_RESET}     # لاگ فایل

💬 توی تلگرامت تایپ کن:  .help

🔒 یادت نره .env و *.session لو نره.

EOF
}

# ──────────────── جریان اصلی ────────────────
main() {
  banner
  ensure_prereqs
  fetch_project
  setup_venv
  prompt_env
  first_login
  install_service
  farewell
}

main "$@"
