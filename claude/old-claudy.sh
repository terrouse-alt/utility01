#!/bin/bash
# Sends a Claude Code event to the OLD_CLAUDY ntfy topic so it shows up on your phone.
# Called by hooks in ~/.claude/settings.json with the event name as $1 and the hook JSON on stdin.
#   attention -> Claude is waiting on you (permission prompt, question, idle)
#   done      -> Claude finished a turn / task
#   error     -> the turn ended on an API error
TOPIC="${CLAUDY_TOPIC:-OLD_CLAUDY}"
EVENT="$1"
INPUT=$(cat)

cwd=$(printf '%s' "$INPUT" | jq -r '.cwd // empty')
project="${cwd##*/}"
[ -z "$project" ] && project="Claude Code"

case "$EVENT" in
  attention)
    title="Claude needs you - $project"
    body=$(printf '%s' "$INPUT" | jq -r '.message // "Claude is waiting for your input."')
    priority=high; tags=bell ;;
  done)
    title="Claude finished - $project"
    body=$(printf '%s' "$INPUT" | jq -r '.last_assistant_message // empty' | tr -s '\n' ' ' | cut -c1-300)
    [ -z "$body" ] && body="Task complete."
    priority=default; tags=white_check_mark ;;
  error)
    title="Claude hit an error - $project"
    body=$(printf '%s' "$INPUT" | jq -r '.error // .message // "The turn stopped on an error."' | cut -c1-300)
    priority=high; tags=warning ;;
  *)
    exit 0 ;;
esac

curl -fsS --max-time 10 \
  -H "Title: $title" -H "Priority: $priority" -H "Tags: $tags" \
  --data-binary "$body" "https://ntfy.sh/$TOPIC" >/dev/null
