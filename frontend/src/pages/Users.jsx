import { useState } from 'react'
import { KeyRound, Pencil, Plus } from 'lucide-react'
import DataTable from '../components/DataTable'
import { Button, Checkbox, ErrorBanner, Input, Modal, PageHeader, Select, Spinner, StatusBadge, useToast } from '../components/ui'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { dateTime, titleCase } from '../lib/format'
import { useAction, useFetch } from '../lib/hooks'

const ROLES = [
  { value: 'VIEWER', label: 'Viewer: can see everything, change nothing' },
  { value: 'MANAGER', label: 'Manager: runs vehicles, drivers, trips and costs' },
  { value: 'ADMIN', label: 'Admin: everything, plus users and deletions' },
]

function UserForm({ user, self, onClose, onSaved }) {
  const editing = Boolean(user)
  const notify = useToast()
  const { busy, error, run } = useAction()
  const [form, setForm] = useState({
    name: user?.name || '', email: user?.email || '', password: '', role: user?.role || 'VIEWER', is_active: user?.is_active ?? true,
  })
  const set = (key) => (e) => setForm({ ...form, [key]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })

  const submit = async (e) => {
    e.preventDefault()
    try {
      if (editing) {
        const body = { name: form.name, role: form.role, is_active: form.is_active }
        if (form.password) body.password = form.password
        await run(() => api.patch(`/users/${user.id}`, body))
        notify('User updated')
      } else {
        await run(() => api.post('/users', form))
        notify('User created. Share the password with them privately.')
      }
      onSaved()
    } catch { /* shown */ }
  }

  return (
    <Modal open title={editing ? 'Edit user' : 'Add user'} onClose={onClose}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button type="submit" form="user-form" busy={busy}>{editing ? 'Save changes' : 'Create user'}</Button></>}>
      <form id="user-form" onSubmit={submit} className="flex flex-col gap-4">
        <ErrorBanner message={error} />
        <Input label="Name" required minLength={2} value={form.name} onChange={set('name')} />
        <Input label="Email" type="email" required disabled={editing} value={form.email} onChange={set('email')}
               hint={editing ? 'Email addresses cannot be changed.' : undefined} />
        <Input label={editing ? 'New password' : 'Password'} type="password" autoComplete="new-password"
               required={!editing} minLength={8} value={form.password} onChange={set('password')}
               hint={editing ? 'Leave empty to keep the current password. Setting one signs the user out everywhere.'
                 : 'At least 8 characters, mixing letters with numbers or symbols.'} />
        <Select label="Role" options={ROLES} value={form.role} onChange={set('role')} disabled={self}
                hint={self ? 'You cannot change your own role.' : 'Changing the role signs the user out so the new role applies.'} />
        {editing && !self && <Checkbox label="Account active" hint="Inactive users cannot sign in." checked={form.is_active} onChange={set('is_active')} />}
      </form>
    </Modal>
  )
}

export default function Users() {
  const { user: me } = useAuth()
  const { data, error, loading, reload } = useFetch('/users')
  const [modal, setModal] = useState(null)
  const close = () => setModal(null)

  return (
    <>
      <PageHeader title="Users" description="Who can sign in, and what each person is allowed to do."
        actions={<Button icon={Plus} onClick={() => setModal({})}>Add user</Button>} />
      <ErrorBanner message={error} onRetry={reload} />
      {loading && !data ? <Spinner /> : (
        <DataTable rows={data || []} searchText={(u) => `${u.name} ${u.email} ${u.role}`} searchPlaceholder="Search name, email or role"
          columns={[
            { key: 'name', header: 'Name', render: (u) => <span className="font-semibold">{u.name}{u.id === me.id && <span className="ml-1.5 font-normal text-muted">(you)</span>}</span> },
            { key: 'email', header: 'Email' },
            { key: 'role', header: 'Role', render: (u) => titleCase(u.role) },
            { key: 'is_active', header: 'Status', render: (u) => <StatusBadge status={u.is_active ? 'AVAILABLE' : 'INACTIVE'} label={u.is_active ? 'Active' : 'Inactive'} /> },
            { key: 'last_login_at', header: 'Last sign-in', render: (u) => <span className="tabular whitespace-nowrap">{u.last_login_at ? dateTime(u.last_login_at) : 'Never'}</span> },
            { key: 'x', header: '', sortable: false, align: 'right', render: (u) => (
              <Button size="sm" variant="ghost" icon={u.id === me.id ? KeyRound : Pencil} onClick={() => setModal({ user: u })} aria-label={`Edit ${u.name}`} />
            ) },
          ]} />
      )}
      {modal && <UserForm user={modal.user} self={modal.user?.id === me.id} onClose={close} onSaved={() => { close(); reload(true) }} />}
    </>
  )
}
