export function formatDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-HK', {
    day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Asia/Hong_Kong',
  })
}
