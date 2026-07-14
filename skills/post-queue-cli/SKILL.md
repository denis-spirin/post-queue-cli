---
name: post-queue-cli
description: Use Post Queue to list connected accounts and list, create, inspect, update, or delete scheduled posts, queues, and queue items.
compatibility: Requires Python 3.11+ and network access to Post Queue.
---

# Post Queue CLI

Run commands from this skill directory. The CLI reads the API key from `.env`
beside this file. If `.env` does not exist, stop and direct the user to
[references/ENV.md](references/ENV.md). Never ask the user to paste an API key
into chat.

    python3 scripts/post_queue.py COMMAND

Account connection, billing, and account settings stay in the browser.

## Commands

    python3 scripts/post_queue.py account list
    python3 scripts/post_queue.py media upload FILE
    python3 scripts/post_queue.py post create --account ACCOUNT_ID --kind KIND --run-at TIMESTAMP [OPTIONS]
    python3 scripts/post_queue.py post list
    python3 scripts/post_queue.py post get GROUP_ID
    python3 scripts/post_queue.py post update GROUP_ID [OPTIONS]
    python3 scripts/post_queue.py post delete GROUP_ID --yes
    python3 scripts/post_queue.py queue create --name NAME --account ACCOUNT_ID [SCHEDULE] [OPTIONS]
    python3 scripts/post_queue.py queue list
    python3 scripts/post_queue.py queue get QUEUE_ID
    python3 scripts/post_queue.py queue update QUEUE_ID [OPTIONS]
    python3 scripts/post_queue.py queue delete QUEUE_ID --yes
    python3 scripts/post_queue.py queue-item add QUEUE_ID --kind KIND [OPTIONS]
    python3 scripts/post_queue.py queue-item update QUEUE_ID ITEM_ID [OPTIONS]
    python3 scripts/post_queue.py queue-item delete QUEUE_ID ITEM_ID --yes

Use `--help` after any resource or command to see its accepted flags. `KIND` is
`text`, `image`, `video`, or `carousel`. A queue schedule is either
`--interval-minutes MINUTES` or `--cron EXPRESSION`.

## Connected accounts

List accounts before creating posts or queues:

    python3 scripts/post_queue.py account list

Use the returned account IDs. Check `supported_post_kinds`,
`image_constraints`, and `max_text_characters` before preparing a post.

## Scheduled posts

Create a text post:

    python3 scripts/post_queue.py post create \
      --account ACCOUNT_ID \
      --kind text \
      --description "Post text" \
      --run-at 2026-07-20T14:00:00Z

Create a video, image, or carousel with local files. Repeat `--media` for a
carousel and `--account` for multiple destinations.

    python3 scripts/post_queue.py post create \
      --account ACCOUNT_ID \
      --kind video \
      --media ./clip.mp4 \
      --description "Caption" \
      --tag launch \
      --run-at 2026-07-20T14:00:00Z

List, inspect, or change posts:

    python3 scripts/post_queue.py post list
    python3 scripts/post_queue.py post get GROUP_ID
    python3 scripts/post_queue.py post update GROUP_ID \
      --description "Revised caption" \
      --run-at 2026-07-21T14:00:00Z

An update returns a new `group_id`. Use that ID afterward. The post kind cannot
change. `--account` adds a destination and `--remove-account` removes one.
Unmentioned destinations remain selected. `--clear-tags` removes all tags.

## Queues

Create an interval queue:

    python3 scripts/post_queue.py queue create \
      --name "Daily posts" \
      --account ACCOUNT_ID \
      --interval-minutes 1440 \
      --next-run-at 2026-07-20T14:00:00Z

Create a cron queue:

    python3 scripts/post_queue.py queue create \
      --name "Weekdays" \
      --account ACCOUNT_ID \
      --cron "0 9 * * 1-5" \
      --timezone America/Toronto

List, inspect, or change queues:

    python3 scripts/post_queue.py queue list
    python3 scripts/post_queue.py queue get QUEUE_ID
    python3 scripts/post_queue.py queue update QUEUE_ID --name "Updated name"

On queue update, `--account` adds a destination and `--remove-account` removes
one. Unmentioned destinations remain selected.

Add or edit a waiting item:

    python3 scripts/post_queue.py queue-item add QUEUE_ID \
      --kind image \
      --media ./image.jpg \
      --description "Caption"
    python3 scripts/post_queue.py queue-item update \
      QUEUE_ID ITEM_ID --description "Revised caption"

The kind and media of a waiting item cannot change.

## Provider options

These flags work on post create, post update, queue create, and queue update:

    --youtube-privacy public|unlisted|private
    --tiktok-privacy PUBLIC_TO_EVERYONE|MUTUAL_FOLLOW_FRIENDS|FOLLOWER_OF_CREATOR|SELF_ONLY
    --tiktok-draft / --no-tiktok-draft
    --tiktok-disable-comment / --no-tiktok-disable-comment
    --tiktok-auto-add-music / --no-tiktok-auto-add-music
    --tiktok-brand-content / --no-tiktok-brand-content
    --tiktok-brand-organic / --no-tiktok-brand-organic
    --tiktok-music-usage-confirmed / --no-tiktok-music-usage-confirmed
    --facebook-draft / --no-facebook-draft

Queue options become defaults for each selected account. TikTok image and
carousel posts require `--tiktok-music-usage-confirmed` and cannot use draft
mode.

## Deletion

Get explicit user confirmation for the exact ID immediately before deletion,
then pass `--yes`:

    python3 scripts/post_queue.py post delete GROUP_ID --yes
    python3 scripts/post_queue.py queue delete QUEUE_ID --yes
    python3 scripts/post_queue.py queue-item delete QUEUE_ID ITEM_ID --yes

Deleting a Post Queue record does not remove a post already published on a
social platform. Deleting a queue affects only waiting items.

Successful output is JSON on stdout. Errors are JSON on stderr.
