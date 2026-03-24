---
name: project_module
description: Core architecture and file structure of the odoo_subscription_manager module (Odoo 17 Community)
type: project
---

# Module: odoo_subscription_manager (Odoo 17.0)

**Technical name:** `odoo_subscription_manager`
**Author:** Esteban Viniegra | Eviniegra Software
**Depends:** base, mail, account, product

## Models

| Model | File | Purpose |
|---|---|---|
| `subscription.plan` | `models/subscription_plan.py` | Plan template (price, billing interval, product) |
| `subscription.subscriber` | `models/subscription_subscriber.py` | Main Kanban entity, linked to res.partner + portal user |
| `subscription.subscription` | `models/subscription_subscription.py` | Individual subscription per subscriber; drives state, invoicing, cron logic |
| `subscription.payment.wizard` | `wizard/subscription_payment_wizard.py` | TransientModel: pay invoice from subscriber form |
| `account.move` (inherited) | `models/account_move.py` | Adds `subscription_id` FK |
| `res.config.settings` (inherited) | `models/res_config_settings.py` | grace_days, penalty_amount, reminder_days |

## States (same for subscriber and subscription)
`draft` → `active` → `pending_payment` → `paused` → `finished`

## Cron Jobs (daily, in `subscription.subscription`)
1. `_cron_generate_invoices` — create invoices when `date_next_invoice <= today`
2. `_cron_check_overdue` — move active→pending_payment + send overdue email
3. `_cron_check_grace_period` — move pending_payment→paused + penalty invoice
4. `_cron_send_payment_reminders` — send reminder N days before due date

## Config Parameters
- `subscription.grace_days` (default 5)
- `subscription.penalty_amount` (default 0.0)
- `subscription.reminder_days` (default 3)

## Security Groups
- `odoo_subscription_manager.group_subscription_user`
- `odoo_subscription_manager.group_subscription_manager`

## Key Design Decisions
- Subscriber state is NOT computed; updated by `_compute_and_set_state()` called from cron/actions
- Invoice FK lives on `account.move.subscription_id`; no separate link model
- Payment wizard auto-reconciles and sends email template `email_template_payment_confirmation`
- `date_next_invoice` captured BEFORE advancing when creating invoice (due date = old next invoice date)

**Why:** Module started from scratch (commit `c8d3299 rollback, empezando desde cero con claude code`). All 17 files generated in one session.
**How to apply:** When adding features, follow existing pattern: cron methods on `subscription.subscription`, state updates via `_compute_and_set_state()` on subscriber.
