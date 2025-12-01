import { FullSlug, resolveRelative } from "../util/path"
import { QuartzPluginData } from "../plugins/vfile"
import { Date, getDate } from "./Date"
import { QuartzComponent, QuartzComponentProps } from "./types"
import { GlobalConfiguration } from "../cfg"

export function byDateAndAlphabetical(
  cfg: GlobalConfiguration,
): (f1: QuartzPluginData, f2: QuartzPluginData) => number {
  return (f1, f2) => {
    if (f1.dates && f2.dates) {
      // sort descending
      return getDate(cfg, f2)!.getTime() - getDate(cfg, f1)!.getTime()
    } else if (f1.dates && !f2.dates) {
      // prioritize files with dates
      return -1
    } else if (!f1.dates && f2.dates) {
      return 1
    }

    // otherwise, sort lexographically by title
    const f1Title = f1.frontmatter?.title.toLowerCase() ?? ""
    const f2Title = f2.frontmatter?.title.toLowerCase() ?? ""
    return f1Title.localeCompare(f2Title)
  }
}

type FolderAwareData = QuartzPluginData & { folderListEntry?: boolean }

const isFolderEntry = (page: QuartzPluginData): page is FolderAwareData =>
  Boolean((page as FolderAwareData).folderListEntry)

type Props = {
  limit?: number
} & QuartzComponentProps

export const PageList: QuartzComponent = ({ cfg, fileData, allFiles, limit }: Props) => {
  const comparator = byDateAndAlphabetical(cfg)
  const folderEntries = allFiles.filter(isFolderEntry).sort(comparator)
  const noteEntries = allFiles.filter((page) => !isFolderEntry(page)).sort(comparator)

  let list = [...folderEntries, ...noteEntries]
  if (limit) {
    list = list.slice(0, limit)
  }

  return (
    <ul class="section-ul">
      {list.map((page) => {
        const title = page.frontmatter?.title
        const tags = page.frontmatter?.tags ?? []
        const folderEntry = isFolderEntry(page)

        return (
          <li class="section-li">
            <div class={`section${folderEntry ? " folder-entry" : ""}`}>
              {folderEntry ? (
                <div class="meta meta-placeholder" aria-hidden="true" />
              ) : (
                page.dates && (
                  <p class="meta">
                    <Date date={getDate(cfg, page)!} locale={cfg.locale} />
                  </p>
                )
              )}
              <div class="desc">
                <h3>
                  <a href={resolveRelative(fileData.slug!, page.slug!)} class="internal">
                    {title}
                  </a>
                </h3>
              </div>
              {!folderEntry && (
                <ul class="tags">
                  {tags.map((tag) => (
                    <li>
                      <a
                        class="internal tag-link"
                        href={resolveRelative(fileData.slug!, `tags/${tag}` as FullSlug)}
                      >
                        {tag}
                      </a>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </li>
        )
      })}
    </ul>
  )
}

PageList.css = `
.section h3 {
  margin: 0;
}

.section > .tags {
  margin: 0;
}

.section.folder-entry {
  grid-template-columns: 6em 3fr;
}

.section.folder-entry > .tags {
  display: none;
}

.section.folder-entry > .meta-placeholder {
  visibility: hidden;
}
`
