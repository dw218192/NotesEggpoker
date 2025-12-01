import { QuartzComponent, QuartzComponentConstructor, QuartzComponentProps } from "../types"
import path from "path"

import style from "../styles/listPage.scss"
import { PageList } from "../PageList"
import { FullSlug, joinSegments, stripSlashes, simplifySlug } from "../../util/path"
import { Root } from "hast"
import { htmlToJsx } from "../../util/jsx"
import { i18n } from "../../i18n"
import { QuartzPluginData } from "../../plugins/vfile"

interface FolderContentOptions {
  /**
   * Whether to display number of folders
   */
  showFolderCount: boolean
}

const defaultOptions: FolderContentOptions = {
  showFolderCount: true,
}

export default ((opts?: Partial<FolderContentOptions>) => {
  const options: FolderContentOptions = { ...defaultOptions, ...opts }

  const FolderContent: QuartzComponent = (props: QuartzComponentProps) => {
    const { tree, fileData, allFiles, cfg } = props
    const folderSlug = stripSlashes(simplifySlug(fileData.slug!))
    const folderParts = folderSlug === "" ? [] : folderSlug.split(path.posix.sep)
    const getParts = (slug: string): string[] => (slug === "" ? [] : slug.split(path.posix.sep))

    const directChildren: (QuartzPluginData & { folderListEntry?: boolean })[] = []
    const foldersWithIndexes = new Set<string>()
    const descendantFolders = new Set<string>()

    for (const file of allFiles) {
      if (!file.slug) {
        continue
      }

      const simplifiedSlug = stripSlashes(simplifySlug(file.slug as FullSlug))
      if (simplifiedSlug === folderSlug) {
        continue
      }

      const fileParts = getParts(simplifiedSlug)
      const isWithinFolder =
        folderParts.length === 0 ||
        (fileParts.length >= folderParts.length &&
          folderParts.every((segment, idx) => fileParts[idx] === segment))
      if (!isWithinFolder) {
        continue
      }

      const relativeParts = fileParts.slice(folderParts.length)
      if (relativeParts.length === 0) {
        continue
      }

      if (relativeParts.length === 1) {
        const rawSlug = stripSlashes(file.slug as string)
        const isFolderIndex = rawSlug.endsWith("index")
        const entry: QuartzPluginData & { folderListEntry?: boolean } = isFolderIndex
          ? { ...file, folderListEntry: true }
          : file
        if (isFolderIndex) {
          foldersWithIndexes.add(simplifiedSlug)
        }
        directChildren.push(entry)
      } else {
        const nextFolder = joinSegments(folderSlug, relativeParts[0])
        descendantFolders.add(nextFolder)
      }
    }

    for (const folder of descendantFolders) {
      if (foldersWithIndexes.has(folder)) {
        continue
      }

      const folderName = folder.split(path.posix.sep).at(-1) ?? folder
      directChildren.push({
        slug: joinSegments(folder, "index") as FullSlug,
        frontmatter: {
          title: folderName,
          tags: [],
        },
        folderListEntry: true,
      })
    }

    const folderEntries = directChildren.filter((entry) => entry.folderListEntry)
    const noteEntries = directChildren.filter((entry) => !entry.folderListEntry)
    const allPagesInFolder = [...folderEntries, ...noteEntries]
    const cssClasses: string[] = fileData.frontmatter?.cssclasses ?? []
    const classes = ["popover-hint", ...cssClasses].join(" ")
    const listProps = {
      ...props,
      allFiles: allPagesInFolder,
    }

    const content =
      (tree as Root).children.length === 0
        ? fileData.description
        : htmlToJsx(fileData.filePath!, tree)

    return (
      <div class={classes}>
        <article>{content}</article>
        <div class="page-listing">
          {options.showFolderCount && (
            <p>
              {i18n(cfg.locale).pages.folderContent.itemsUnderFolder({
                count: allPagesInFolder.length,
              })}
            </p>
          )}
          <div>
            <PageList {...listProps} />
          </div>
        </div>
      </div>
    )
  }

  FolderContent.css = style + PageList.css
  return FolderContent
}) satisfies QuartzComponentConstructor
