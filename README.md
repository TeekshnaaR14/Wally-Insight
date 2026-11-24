<div align="center">
<img src="web/assets/wally.png" alt="Wally Logo" width="100" height="100" />
<h1 align="center">Wally</h1>
</div>

<p align="center">
<a href="https://github.com/polius/Wally/actions/workflows/release.yml"><img src="https://github.com/polius/Wally/actions/workflows/release.yml/badge.svg" alt="Release"></a>&nbsp;<a href="https://github.com/polius/Wally/releases"><img alt="GitHub Release" src="https://img.shields.io/github/v/release/polius/Wally"></a>&nbsp;<a href="https://hub.docker.com/r/poliuscorp/wally"><img alt="Docker Pulls" src="https://img.shields.io/docker/pulls/poliuscorp/wally"></a>
</p>

<br>

<p align="center">
<b>Wally</b> is a lightweight, self-hosted expense tracker that makes it easy to manage your finances.
</p>

<br>

| | Desktop View | Mobile View |
| --- | --- | --- |
| Light | <img src="assets/dashboards-light.png?version=1.14" alt="Dashboards Light" /> | <img src="assets/dashboards-light-mobile.png?version=1.14" alt="Dashboards Light Mobile" /> |
| Dark | <img src="assets/dashboards-dark.png?version=1.14" alt="Dashboards Dark" /> | <img src="assets/dashboards-dark-mobile.png?version=1.14" alt="Dashboards Dark Mobile" /> |

<details>
<summary>Expand this to see screenshots of other pages</summary>

| | Desktop View | Mobile View |
| --- | --- | --- |
| Transactions Light | <img src="assets/transactions-light.png?version=1.14" alt="Transactions Light" /> | <img src="assets/transactions-light-mobile.png?version=1.14" alt="Transactions Light Mobile " /> |
| Transactions Dark | <img src="assets/transactions-dark.png?version=1.14" alt="Transactions Dark" /> | <img src="assets/transactions-dark-mobile.png?version=1.14" alt="Transactions Dark Mobile" /> |
| Settings Light | <img src="assets/settings-light.png?version=1.14" alt="Settings Light" /> | <img src="assets/settings-light-mobile.png?version=1.14" alt="Settings Light Mobile" /> |
| Settings Dark | <img src="assets/settings-dark.png?version=1.14" alt="Settings Dark" /> | <img src="assets/settings-dark-mobile.png?version=1.14" alt="Settings Dark Mobile" /> |
| Login Light | <img src="assets/login-light.png?version=1.14" alt="Login Light" /> | <img src="assets/login-light-mobile.png?version=1.14" alt="Login Light Mobile" /> |
| Login Dark | <img src="assets/login-dark.png?version=1.14" alt="Login Dark" /> | <img src="assets/login-dark-mobile.png?version=1.14" alt="Login Dark Mobile" /> |

</details>

## Quick Demo

Want to try Wally quickly? Run this command to start a demo instance with sample data:

```bash
docker run --rm -e DEMO=true -p 80:80 poliuscorp/wally
```

Then open [http://localhost](http://localhost) in your browser.

> **Note:** This runs in demo mode with pre-loaded data. Your changes won't persist after stopping the container. For a permanent installation, see below.

## Installation

### Run with Docker CLI

```bash
docker run -d \
  --name wally \
  -p 80:80 \
  -v $(pwd):/wally/data \
  poliuscorp/wally
```

- The `-v` flag ensures your data persists when the container restarts or is updated.
- Replace `$(pwd)` with the folder on your host where you want Wally to store its database.

Access Wally at: [http://localhost](http://localhost)

### Run with Docker Compose

```yaml
services:
  wally:
    image: poliuscorp/wally
    container_name: wally
    restart: unless-stopped
    ports:
      - "80:80"
    volumes:
      - $(pwd):/wally/data
```

- Replace `$(pwd)` with the folder on your host where you want Wally to store its database.

Access Wally at: [http://localhost](http://localhost)

## Environment variables

Wally supports the following environment variables:

| Variable | Sample Value | Details |
| --- | --- | --- |
| DEMO | true | Pre-loads the app with random demo data |

## Data Import / Export

Wally supports CSV import/export. The file must contain the following columns:

```
name,category,type,amount,date,tags
```

**Example**

```
name,category,type,amount,date,tags
An expense,Rent,expense,1000.0,2025-08-01,
An income,Salary,income,2000.0,2025-08-01,"Tag1,Tag2"
```

- `type` can be `income` or `expense`.
- `tags` are optional and can be multiple, separated by commas.

This can be done directly from the **Settings** page.

## Acknowledgement

Wally has been built using [ExpenseOwl](https://github.com/Tanq16/ExpenseOwl) as an inspiration, and many ideas were derived from that project.

### Key Differences

- **Login page**: An optional login page was added. This enhancement provides an additional layer of security for those who prefer to protect Wally with authentication.

- **Dashboards page**: A "Change" button was introduced to switch between different graphs. Users can now view expense trends not only on a monthly basis but also across an entire year. This replaces the doughnut chart with a line graph, allowing tracking of a specific category (like Restaurants) over time.

- **Transactions page**: The table was replaced with one built using AG Grid, adding search, column sorting, and per-column filtering. A footer was also added to display the total number of rows, total income, and total expenses for the current view.

- **Recurring transactions**: Editing and deletion were enhanced, allowing users to specify whether changes apply to all existing transactions or only future ones.

- **Backend rewrite**: The backend was rewritten from Go to Python using FastAPI. This change provides a built-in API with interactive documentation at http://localhost/api/docs, making it easier to integrate external tools or automate tasks.

- **Dark theme improvements**: The dark mode color palette was refined for improved visual consistency and better contrast, resulting in a more balanced and neutral appearance.

- **Storage changes**: Wally uses SQLite as its data storage solution, while ExpenseOwl offers either JSON files or PostgreSQL. For the type and scale of data this application handles, SQLite was selected as a more suitable and efficient choice.

- **API Keys management**: When login is enabled, users can create and manage API keys directly from the Settings page. This allows secure, token-based access to Wally's API for external integrations and automation.

- **Internationalization**: Wally supports translation into over 10 languages, making it accessible to users worldwide. 

## Personalized insights

Open **Insights** from the Wally navigation. Wally calculates these results locally
from its own database. The page refreshes when opened or refocused, and every
minute while it is visible.

- **Top spending this month** shows the three largest expense totals by category
  from the start of the month through today.
- **Biggest spending change** compares the same number of elapsed days in this
  month and last month, capped by the shorter period. It shows the category
  with the largest absolute change when both periods contain expenses and at least
  one category changed.
- **Budget closest to its limit** shows the budget with the highest share of
  its limit used, including budgets already over their limit. It uses the
  budget’s weekly or monthly window, counts expenses through today, and shows
  the existing end-of-period forecast when available.
- **Estimated monthly subscription cost** uses the Bills & Subscriptions
  monthly estimate for recurring expenses marked as subscriptions with a
  remaining scheduled charge.

Cards appear as data becomes available. A fresh account with no expenses or
subscriptions shows an empty state. Amounts use the configured Wally currency.

### Demo and verification

From a fresh local instance, open **Insights** to see the empty state. Add
two Food expenses for 20 and 75, one on the first day of last month and one
on the first day of this month. Add a monthly Food budget with a limit of
100 and a quarterly recurring subscription for 36. Use a different category
or a future start date for the subscription to keep the Food totals isolated.
Return to **Insights**. Food should show 75 this month, a 55 increase from
last month, and 75 of 100 used. The subscription estimate should be 12 per
month. Add another Food expense for 7 and return to **Insights** to see 82
in spending and budget usage.

Run the backend tests from the repository root with
`python -m pip install -r api/requirements.txt pytest` followed by
`python -m pytest api/tests`.
