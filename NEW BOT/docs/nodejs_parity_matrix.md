# NodeJS -> Python Parity Matrix

Source of truth: `src/bot/bot.service.ts`.

## Commands

| NodeJS command         | Python status | Notes                                        |
| ---------------------- | ------------- | -------------------------------------------- |
| `/start`               | PASS          | Renders main menu with access checks         |
| `/menu`                | PASS          | Same as `/start`                             |
| `/cancel`              | PASS          | Resets user state to `IDLE`                  |
| `/import_groups`       | PASS          | Imports remote groups into local `UserGroup` |
| `/adduser <id> <days>` | PASS          | Super admin only                             |
| `/ban <id>`            | PASS          | Super admin only                             |
| `/info`                | PASS          | Super admin stats or user expiry             |
| `/id`                  | PASS          | Returns caller Telegram id                   |

## Static callbacks

| NodeJS callback       | Python status | Notes                                   |
| --------------------- | ------------- | --------------------------------------- |
| `login`               | PASS          | Starts phone flow                       |
| `select_groups`       | PASS          | Opens group selection                   |
| `add_group`           | PASS          | Opens remote import choices             |
| `deselect_all_groups` | PASS          | Removes all selected groups             |
| `start_broadcast`     | PASS          | Requires configured message+interval    |
| `stop_broadcast`      | PASS          | Disables config                         |
| `send_message`        | PASS          | Enters message capture state            |
| `search_messages`     | PASS          | Informational placeholder branch        |
| `restart_bot`         | PASS          | Menu refresh/restart branch             |
| `full_manual`         | PASS          | Full manual selector                    |
| `sent_messages`       | PASS          | Shows recent local sent message history |
| `about_bot`           | PASS          | About menu                              |
| `about_bot_text`      | PASS          | Text manual                             |
| `about_bot_video`     | PASS          | Sends manual video if configured        |
| `back_to_menu`        | PASS          | Returns to main menu                    |
| `set_interval_custom` | PASS          | Switches to manual interval input       |
| `cancel_broadcast`    | PASS          | Clears message draft and state          |
| `admin_panel`         | PASS          | Super admin panel                       |
| `admin_announce`      | PASS          | Enters broadcast announce state         |

## Pattern callbacks

| NodeJS callback pattern         | Python status | Notes                         |
| ------------------------------- | ------------- | ----------------------------- |
| `import_group_<id>`             | PASS          | Adds selected remote group    |
| `sent_messages_page_<n>`        | PASS          | History pagination            |
| `history_view_<id>`             | PASS          | History detail view           |
| `history_delete_<id>`           | PASS          | History item deletion         |
| `set_interval_<minutes>`        | PASS          | Stores config and activates   |
| `admin_panel_<filter>_page_<n>` | PASS          | Admin list filters/pagination |
| `admin_user_<id>`               | PASS          | User detail view              |
| `admin_add_month_<id>`          | PASS          | +30 days expiry               |
| `admin_sub_month_<id>`          | PASS          | -30 days expiry               |
| `admin_block_<id>`              | PASS          | Removes allowed user          |

## User states

| State                    | Python status | Notes                               |
| ------------------------ | ------------- | ----------------------------------- |
| `IDLE`                   | PASS          | Default state                       |
| `WAITING_PHONE`          | PASS          | Phone text or contact accepted      |
| `WAITING_CODE`           | PASS          | Spaced code normalization supported |
| `WAITING_PASSWORD`       | PASS          | 2FA path                            |
| `WAITING_BROADCAST_MSG`  | PASS          | Captures message                    |
| `WAITING_INTERVAL`       | PASS          | Preset/custom interval              |
| `WAITING_ADMIN_ANNOUNCE` | PASS          | Admin announcement input            |

## Access outcomes

| Case                        | Python status | Notes                            |
| --------------------------- | ------------- | -------------------------------- |
| Super admin bypass          | PASS          | Username whitelist bypass        |
| Unknown user pending record | PASS          | Auto-created with expired access |
| Expired user denied         | PASS          | Receives expiration warning      |
