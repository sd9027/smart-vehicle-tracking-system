import { useMemo, useState } from 'react'
import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Search } from 'lucide-react'
import { EmptyState } from './ui'

/**
 * Searchable, sortable, paginated table.
 * columns: [{ key, header, render?(row), sortValue?(row), align?, className? }]
 * searchText(row) returns the text that the search box matches against.
 */
export default function DataTable({
  columns, rows, searchText, searchPlaceholder = 'Search', emptyTitle = 'Nothing here yet',
  emptyText, toolbar, pageSize = 15, rowKey = (r) => r.id,
}) {
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState(null) // { key, dir }
  const [page, setPage] = useState(0)

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    let list = rows || []
    if (q && searchText) list = list.filter((r) => searchText(r).toLowerCase().includes(q))
    if (sort) {
      const col = columns.find((c) => c.key === sort.key)
      const value = col?.sortValue || ((r) => r[sort.key])
      list = [...list].sort((a, b) => {
        const va = value(a)
        const vb = value(b)
        if (va === vb) return 0
        if (va === null || va === undefined) return 1
        if (vb === null || vb === undefined) return -1
        return (va > vb ? 1 : -1) * (sort.dir === 'asc' ? 1 : -1)
      })
    }
    return list
  }, [rows, query, sort, columns, searchText])

  const pages = Math.max(1, Math.ceil(filtered.length / pageSize))
  const current = Math.min(page, pages - 1)
  const visible = filtered.slice(current * pageSize, current * pageSize + pageSize)

  const toggleSort = (key) => {
    setSort((s) => (s?.key === key ? (s.dir === 'asc' ? { key, dir: 'desc' } : null) : { key, dir: 'asc' }))
  }

  return (
    <div className="rounded-lg border border-line bg-white">
      {(searchText || toolbar) && (
        <div className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3">
          {searchText && (
            <label className="relative min-w-52 flex-1 sm:max-w-xs">
              <span className="sr-only">{searchPlaceholder}</span>
              <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" aria-hidden />
              <input
                value={query}
                onChange={(e) => { setQuery(e.target.value); setPage(0) }}
                placeholder={searchPlaceholder}
                className="h-9 w-full rounded-md border border-line pl-9 pr-3 text-sm focus:border-route focus:outline-none focus:ring-2 focus:ring-route/20"
              />
            </label>
          )}
          {toolbar}
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-muted">
              {columns.map((c) => (
                <th key={c.key} scope="col" className={`whitespace-nowrap px-4 py-2.5 font-semibold ${c.align === 'right' ? 'text-right' : ''}`}>
                  {c.sortable === false ? c.header : (
                    <button type="button" onClick={() => toggleSort(c.key)} className="inline-flex items-center gap-1 hover:text-asphalt">
                      {c.header}
                      {sort?.key === c.key && (sort.dir === 'asc' ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />)}
                    </button>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((row) => (
              <tr key={rowKey(row)} className="border-b border-line/70 last:border-0 hover:bg-surface/60">
                {columns.map((c) => (
                  <td key={c.key} className={`px-4 py-2.5 align-middle ${c.align === 'right' ? 'text-right tabular' : ''} ${c.className || ''}`}>
                    {c.render ? c.render(row) : row[c.key] ?? '-'}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {visible.length === 0 && (
          <EmptyState title={query ? `No results for "${query}"` : emptyTitle}>{query ? 'Try a different search.' : emptyText}</EmptyState>
        )}
      </div>

      {pages > 1 && (
        <div className="flex items-center justify-between border-t border-line px-4 py-2 text-sm text-muted">
          <span className="tabular">{current * pageSize + 1} to {Math.min(filtered.length, (current + 1) * pageSize)} of {filtered.length}</span>
          <div className="flex gap-1">
            <button type="button" aria-label="Previous page" disabled={current === 0} onClick={() => setPage(current - 1)} className="rounded p-1 hover:bg-surface disabled:opacity-40"><ChevronLeft className="size-4" /></button>
            <button type="button" aria-label="Next page" disabled={current >= pages - 1} onClick={() => setPage(current + 1)} className="rounded p-1 hover:bg-surface disabled:opacity-40"><ChevronRight className="size-4" /></button>
          </div>
        </div>
      )}
    </div>
  )
}
