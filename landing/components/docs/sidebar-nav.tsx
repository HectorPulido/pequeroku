"use client"

import type React from "react"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { ChevronRight } from "lucide-react"
import { cn } from "@/lib/utils"

const navItems = [
  {
    title: "Home",
    href: "/docs",
  },
  {
    title: "Features",
    href: "/docs#features",
  },
  {
    title: "Technology Stack",
    href: "/docs#stack",
  },
  {
    title: "Self-Hosting",
    href: "/docs#self-hosting",
  },
]

export function SidebarNav() {
  const pathname = usePathname()

  const handleClick = (e: React.MouseEvent<HTMLAnchorElement>, href: string) => {
    if (href.startsWith("#")) {
      e.preventDefault()
      const element = document.querySelector(href)
      if (element) {
        element.scrollIntoView({ behavior: "smooth" })
      }
    } else if (href.includes("#")) {
      e.preventDefault()
      const [path, hash] = href.split("#")
      if (pathname === path) {
        const element = document.querySelector(`#${hash}`)
        if (element) {
          element.scrollIntoView({ behavior: "smooth" })
        }
      } else {
        window.location.href = href
      }
    }
  }

  return (
    <nav className="flex flex-col gap-2">
      {navItems.map((item) => {
        const isActive = pathname === item.href || (item.href.includes("#") && pathname === item.href.split("#")[0])

        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={(e) => handleClick(e, item.href)}
            className={cn(
              "flex w-full cursor-pointer items-center justify-between gap-2 text-left text-sm transition-colors duration-150 hover:text-foreground focus:text-foreground focus:outline-none",
              isActive ? "font-medium text-foreground" : "text-muted-foreground",
            )}
          >
            {item.title}
            <ChevronRight className={cn("size-3 shrink-0", isActive ? "opacity-100" : "opacity-0")} />
          </Link>
        )
      })}
    </nav>
  )
}
