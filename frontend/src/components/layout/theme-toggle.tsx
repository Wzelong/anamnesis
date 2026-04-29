"use client"

import { Moon, Sun } from "lucide-react"
import { useTheme } from "next-themes"
import { Button } from "@/components/ui/button"

export function ThemeToggle() {
  const { setTheme, theme, resolvedTheme } = useTheme()

  const toggleTheme = () => {
    const current = theme === "system" ? resolvedTheme : theme
    setTheme(current === "dark" ? "light" : "dark")
  }

  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={toggleTheme}
      className="cursor-pointer h-7 w-7"
    >
      <Sun className="size-3.5 rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0" />
      <Moon className="absolute size-3.5 rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100" />
    </Button>
  )
}
