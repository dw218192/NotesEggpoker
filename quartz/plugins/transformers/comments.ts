import { QuartzTransformerPlugin } from "../types"
import { Root } from "hast"
import { select } from "hast-util-select"
import { visit } from "unist-util-visit"

export interface Options {
    commentServerURL: string
}

export const Comments: QuartzTransformerPlugin<Partial<Options> | undefined> = (userOpts) => {
    const opts = { ...userOpts }
    return {
        name: "Comments",
        htmlPlugins() {
            return [
                // () => {
                //     return (tree: Root, file) => {
                //         select()
                //         visit(tree, "element", (node, index, parent) => {
                //             if (node.tagName === "a" && parent && parent.tagName === "li") {
                //                 const href = node.properties?.href;
                //                 // make sure the link is internal
                //                 if (!href || href.startsWith("http")) {
                //                     return;
                //                 }
                //                 node.properties.onclick = "window.location.reload()";                                
                //             }
                //         });
                //     }
                // }
            ]
        },
        externalResources() {
            return {
                css: [],
                js: [
                    {
                        loadTime: "afterDOMReady",
                        script: `
                            function initTwikoo() {
                                console.log('reloading comments');
                                const hasComments = document.getElementById('comments');
                                if (hasComments && typeof twikoo !== 'undefined') {
                                    hasComments.innerHTML = '';
                                    twikoo.init({
                                        envId: '${opts.commentServerURL}',
                                        el: '#comments',
                                        lang: 'en-US',
                                    });
                                }
                            }
                            
                            const script = document.createElement('script');
                            script.src = '/static/twikoo.all.min.js';

                            document.head.appendChild(script).onload = function () {
                                const css = document.createElement('link');
                                css.rel = 'stylesheet';
                                css.href = '/static/twikoo.css';
    
                                document.head.appendChild(css).onload = function () {
                                    document.addEventListener('nav', initTwikoo);
                                    initTwikoo();
                                };
                            };
                        `,
                        contentType: "inline",
                        spaPreserve: true,
                    }
                ],
            }
        }
    }
};