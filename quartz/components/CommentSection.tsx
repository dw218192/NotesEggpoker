import { QuartzComponent, QuartzComponentConstructor, QuartzComponentProps } from "./types"

const CommentSection: QuartzComponent = ({ fileData, displayClass }: QuartzComponentProps) => {
    return (
        <div class={displayClass}>
        <div id="comments"></div>
        </div>
    )
}

export default (() => CommentSection) satisfies QuartzComponentConstructor
