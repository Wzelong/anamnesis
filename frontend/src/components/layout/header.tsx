"use client"

import Image from "next/image"
import { Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { ThemeToggle } from "./theme-toggle"

export function Header() {
  return (
    <header className="fixed top-0 left-0 right-0 h-12 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80 flex items-center z-50">
      <div className="pl-2 flex items-center gap-1">
        <Image
          src="/logo.png"
          alt="Anamnesis"
          width={30}
          height={30}
          className="size-[30px]"
        />
        <span className="font-semibold text-sm">Anamnesis</span>
      </div>

      <div className="flex-1" />

      <div className="flex items-center gap-1 pr-3">
        <ThemeToggle />
        <AlertDialog>
          <AlertDialogTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="cursor-pointer h-7 w-7 hover:text-destructive"
            >
              <Trash2 className="size-3.5" />
            </Button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Reset working state?</AlertDialogTitle>
              <AlertDialogDescription>
                This will delete all augmentation sessions, proposals, and
                decisions from the local database. FHIR resources already
                written to the server will not be affected.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Cancel</AlertDialogCancel>
              <AlertDialogAction>Reset</AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
    </header>
  )
}
