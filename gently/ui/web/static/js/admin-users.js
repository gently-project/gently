(function() {
    const app = document.getElementById('admin-users-app');
    const tbody = document.getElementById('admin-users-tbody');
    const form = document.getElementById('admin-user-create');
    const statusEl = document.getElementById('admin-users-status');
    const currentUser = app ? app.dataset.currentUser : '';

    function setStatus(text, tone) {
        if (!statusEl) return;
        statusEl.textContent = text || '';
        statusEl.dataset.tone = tone || '';
    }

    async function requestJson(url, options) {
        const response = await fetch(url, Object.assign({
            headers: { 'Content-Type': 'application/json' },
        }, options || {}));
        const data = await response.json().catch(() => ({}));
        if (!response.ok || data.error) {
            throw new Error(data.error || `Request failed: ${response.status}`);
        }
        return data;
    }

    function roleSelect(user) {
        const select = document.createElement('select');
        select.className = 'settings-input admin-role-select';
        ['viewer', 'operator', 'admin'].forEach(role => {
            const option = document.createElement('option');
            option.value = role;
            option.textContent = role;
            option.selected = role === user.role;
            select.appendChild(option);
        });
        select.addEventListener('change', async () => {
            setStatus('Saving...', '');
            try {
                await requestJson(`/api/auth/users/${encodeURIComponent(user.username)}`, {
                    method: 'PATCH',
                    body: JSON.stringify({ role: select.value }),
                });
                setStatus('Role saved', 'ok');
                await loadUsers();
            } catch (error) {
                select.value = user.role;
                setStatus(error.message, 'error');
            }
        });
        return select;
    }

    function passwordReset(user) {
        const wrap = document.createElement('div');
        wrap.className = 'admin-password-reset';

        const input = document.createElement('input');
        input.className = 'settings-input';
        input.type = 'password';
        input.placeholder = 'New password';
        input.autocomplete = 'new-password';

        const button = document.createElement('button');
        button.className = 'admin-secondary-btn';
        button.type = 'button';
        button.textContent = 'Reset';
        button.addEventListener('click', async () => {
            if (!input.value) {
                setStatus('Password required', 'error');
                return;
            }
            setStatus('Saving...', '');
            try {
                await requestJson(`/api/auth/users/${encodeURIComponent(user.username)}`, {
                    method: 'PATCH',
                    body: JSON.stringify({ password: input.value }),
                });
                input.value = '';
                setStatus('Password reset', 'ok');
            } catch (error) {
                setStatus(error.message, 'error');
            }
        });

        wrap.append(input, button);
        return wrap;
    }

    function deleteButton(user) {
        const button = document.createElement('button');
        button.className = 'admin-danger-btn';
        button.type = 'button';
        button.textContent = 'Delete';
        button.disabled = user.username === currentUser;
        button.title = button.disabled ? 'Cannot delete the current signed-in user' : 'Delete user';
        button.addEventListener('click', async () => {
            if (!window.confirm(`Delete user "${user.username}"?`)) return;
            setStatus('Deleting...', '');
            try {
                await requestJson(`/api/auth/users/${encodeURIComponent(user.username)}`, {
                    method: 'DELETE',
                });
                setStatus('User deleted', 'ok');
                await loadUsers();
            } catch (error) {
                setStatus(error.message, 'error');
            }
        });
        return button;
    }

    function renderUsers(users) {
        tbody.innerHTML = '';
        if (!users.length) {
            const row = document.createElement('tr');
            const cell = document.createElement('td');
            cell.colSpan = 4;
            cell.className = 'admin-users-empty';
            cell.textContent = 'No users';
            row.appendChild(cell);
            tbody.appendChild(row);
            return;
        }

        users.forEach(user => {
            const row = document.createElement('tr');

            const nameCell = document.createElement('td');
            nameCell.className = 'admin-users-name';
            nameCell.textContent = user.username;
            if (user.username === currentUser) {
                const badge = document.createElement('span');
                badge.className = 'admin-current-user';
                badge.textContent = 'current';
                nameCell.appendChild(badge);
            }

            const roleCell = document.createElement('td');
            roleCell.appendChild(roleSelect(user));

            const passwordCell = document.createElement('td');
            passwordCell.appendChild(passwordReset(user));

            const actionsCell = document.createElement('td');
            actionsCell.className = 'admin-users-actions';
            actionsCell.appendChild(deleteButton(user));

            row.append(nameCell, roleCell, passwordCell, actionsCell);
            tbody.appendChild(row);
        });
    }

    async function loadUsers() {
        try {
            const data = await requestJson('/api/auth/users');
            renderUsers(data.users || []);
        } catch (error) {
            setStatus(error.message, 'error');
        }
    }

    if (form) {
        form.addEventListener('submit', async event => {
            event.preventDefault();
            const payload = Object.fromEntries(new FormData(form).entries());
            setStatus('Creating...', '');
            try {
                await requestJson('/api/auth/users', {
                    method: 'POST',
                    body: JSON.stringify(payload),
                });
                form.reset();
                setStatus('User created', 'ok');
                await loadUsers();
            } catch (error) {
                setStatus(error.message, 'error');
            }
        });
    }

    document.addEventListener('DOMContentLoaded', loadUsers);
})();
