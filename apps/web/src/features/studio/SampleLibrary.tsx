export interface SoundCatalogEntry { preset_id: string; style: string; instrument_family: string; role: string; low_midi: number; high_midi: number; reviewed: boolean; license_id: string; attribution_required: boolean }

export function SampleLibrary({ entries, onChoose }: { entries: SoundCatalogEntry[]; onChoose?: ((entry: SoundCatalogEntry) => void) | undefined }) {
  if (entries.length === 0) return <section className="dock-empty"><h3>本地审核音色库为空</h3><p>这里只展示内置 Style Pack 已审核条目，不会联网搜索。</p></section>;
  return <section className="sample-library" aria-label="本地审核音色库">{entries.map((entry) => <article key={`${entry.style}:${entry.preset_id}`}><div><strong>{entry.instrument_family}</strong><span>{entry.style} · {entry.role} · {entry.license_id}</span></div>{onChoose && <button type="button" onClick={() => onChoose(entry)}>用于所选轨道</button>}</article>)}</section>;
}
