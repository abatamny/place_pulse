# PlacePulse demonstration script

This is a short recording checklist, not application seed data. Create the demo users and content through the UI before or during the recording.

## Before recording

1. Keep the private `.env` file in place with the OpenAI-compatible `qwen3.7-plus` settings. Never show the key on screen.
2. Run `docker compose up --build -d` and confirm <http://localhost:8080/api/health> reports healthy.
3. Prepare a small valid JPEG or PNG and, if desired, a video shorter than 15 seconds and 10 MB.
4. Open a second private/incognito browser window for the second user.

## Suggested 4–6 minute walkthrough

1. Show the GitHub repository, README, Compose architecture, and green CI workflow.
2. Register and verify the first user, log in, allow location sharing, and point out the detected place and VISITOR rank.
3. Open KNOCK, post a safe message, refresh/reconnect, and show that history remains.
4. Open DIG, upload approved media, and briefly explain validation, moderation, and 24-hour expiry.
5. If three recent DIGs are available at the same place, show the generated Explore memory, like it, and add a comment.
6. Open Forum, create an anonymous post, and show that the public identity is `Anonymous` while the post remains in **My posts**.
7. In the second window, register a second user. In Messages, search for that user, send a DM, and show the live unread notification in the other window.
8. Log out and show that protected content is no longer accessible.
9. End with the test command/result and the risk-assessment document.

## Submission check

- Keep the recording short and readable at normal playback speed.
- Do not display `.env`, API credentials, phone numbers you consider private, or Azure secrets.
- Upload the video to the course-approved location and replace the placeholder in `final-report.md` with its link.
