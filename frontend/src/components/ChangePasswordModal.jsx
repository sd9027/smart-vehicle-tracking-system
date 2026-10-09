import { useState } from 'react'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { useAction } from '../lib/hooks'
import { Button, ErrorBanner, Input, Modal, useToast } from './ui'

export default function ChangePasswordModal({ open, onClose }) {
  const { applyToken } = useAuth()
  const notify = useToast()
  const { busy, error, setError, run } = useAction()
  const [form, setForm] = useState({ current: '', next: '', confirm: '' })

  const close = () => { setForm({ current: '', next: '', confirm: '' }); setError(''); onClose() }

  const submit = async (e) => {
    e.preventDefault()
    if (form.next !== form.confirm) { setError('The new passwords do not match.'); return }
    try {
      const { data } = await run(() => api.post('/auth/change-password', {
        current_password: form.current, new_password: form.next,
      }))
      applyToken(data)
      notify('Password changed. Other sessions were signed out.')
      close()
    } catch { /* shown via error */ }
  }

  return (
    <Modal open={open} title="Change password" onClose={close}
      footer={<><Button variant="secondary" onClick={close}>Cancel</Button><Button type="submit" form="pw-form" busy={busy}>Change password</Button></>}>
      <form id="pw-form" onSubmit={submit} className="flex flex-col gap-4">
        <ErrorBanner message={error} />
        <Input label="Current password" type="password" autoComplete="current-password" required value={form.current} onChange={(e) => setForm({ ...form, current: e.target.value })} />
        <Input label="New password" type="password" autoComplete="new-password" required minLength={8} hint="At least 8 characters, mixing letters with numbers or symbols." value={form.next} onChange={(e) => setForm({ ...form, next: e.target.value })} />
        <Input label="Confirm new password" type="password" autoComplete="new-password" required value={form.confirm} onChange={(e) => setForm({ ...form, confirm: e.target.value })} />
      </form>
    </Modal>
  )
}
