const insightsStatus = document.getElementById('insightsStatus');
const insightsCards = document.getElementById('insightsCards');
const insightsLogout = document.getElementById('insightsLogout');
let refreshing = false;

async function fetchInsightsData(path) {
    const response = await fetch(`/api${path}`, { cache: 'no-store' });
    if (response.status === 401) {
        window.location.assign('/login');
    }
    if (!response.ok) {
        throw new Error(`Unable to load ${path}`);
    }
    return response.json();
}

function addInsightCard(container, title, details) {
    const column = document.createElement('div');
    column.className = 'col';
    const card = document.createElement('section');
    card.className = 'card card-body h-100';
    const heading = document.createElement('h2');
    heading.className = 'h5 card-title';
    heading.textContent = title;
    const list = document.createElement('ul');
    list.className = 'list-unstyled mb-0';
    for (const detail of details) {
        const item = document.createElement('li');
        item.textContent = detail;
        list.append(item);
    }
    card.append(heading, list);
    column.append(card);
    container.append(column);
}

function renderInsights(insights, currency) {
    const symbol = currency.currencies.find(item => item.name === currency.selected)?.symbol;
    const formatter = new Intl.NumberFormat(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    });
    function money(value) {
        const amount = formatter.format(value);
        if (!symbol) return amount;
        return currency.position === 'left' ? `${symbol}${amount}` : `${amount} ${symbol}`;
    }

    const cards = document.createDocumentFragment();
    if (insights.top_categories.length) {
        addInsightCard(cards, 'Top spending this month', insights.top_categories.map(
            item => `${item.category} · ${money(item.amount)}`
        ));
    }
    const change = insights.biggest_change;
    if (change) {
        const direction = Number(change.change) > 0 ? 'more' : 'less';
        addInsightCard(cards, 'Biggest spending change', [
            `${change.category} · ${money(Math.abs(change.change))} ${direction}`,
            `${money(change.current)} this month vs. ${money(change.previous)} last month over the same number of days`,
        ]);
    }
    const budget = insights.closest_budget;
    if (budget) {
        const details = [`${budget.category} · ${money(budget.spent)} of ${money(budget.limit)} (${budget.period})`];
        if (budget.forecast !== null) {
            details.push(`Projected at period end · ${money(budget.forecast)}`);
        }
        addInsightCard(cards, 'Budget closest to its limit', details);
    }
    if (insights.monthly_subscription_cost !== null) {
        addInsightCard(cards, 'Estimated monthly subscription cost', [money(insights.monthly_subscription_cost)]);
    }
    const hasInsights = cards.hasChildNodes();
    insightsCards.replaceChildren(cards);
    insightsStatus.hidden = hasInsights;
    insightsStatus.textContent = hasInsights ? '' : 'There isn’t enough data for insights yet. Add an expense or mark a recurring payment as a subscription.';
}

async function refreshInsights() {
    if (refreshing || document.hidden) return;
    refreshing = true;
    try {
        const [insights, currency, loginEnabled] = await Promise.all([
            fetchInsightsData('/insights'),
            fetchInsightsData('/currency'),
            fetchInsightsData('/login/check'),
        ]);
        insightsLogout.hidden = !loginEnabled;
        renderInsights(insights, currency);
    } catch {
        insightsCards.replaceChildren();
        insightsStatus.hidden = false;
        insightsStatus.textContent = 'Unable to load insights. Reload the page to try again.';
    } finally {
        refreshing = false;
    }
}

insightsLogout.addEventListener('click', async () => {
    try {
        const response = await fetch('/api/logout', { method: 'POST' });
        if (!response.ok) throw new Error('Unable to log out');
        window.location.assign('/login');
    } catch {
        insightsStatus.hidden = false;
        insightsStatus.textContent = 'Unable to log out. Please try again.';
    }
});
window.addEventListener('pageshow', refreshInsights);
window.addEventListener('focus', refreshInsights);
document.addEventListener('visibilitychange', refreshInsights);
window.setInterval(refreshInsights, 60_000);
