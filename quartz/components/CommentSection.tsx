import { QuartzComponent, QuartzComponentConstructor, QuartzComponentProps } from "./types"

const CommentSection: QuartzComponent = ({ fileData, displayClass }: QuartzComponentProps) => {
    return ( <div id="remark42"></div> )
}

export default (() => CommentSection) satisfies QuartzComponentConstructor
