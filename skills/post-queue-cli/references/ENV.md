# API key setup

1. Create an API key at <https://post-queue.com/api-keys>. The site shows the
   key once.
2. Open a terminal in the installed skill directory, the directory containing
   `SKILL.md`.
3. Create the local environment file:

       cp .env.example .env

4. Open `.env` and paste the key after `POST_QUEUE_API_KEY=`.
5. Restrict access to the file:

       chmod 600 .env

Do not paste the key into chat or commit `.env`.
