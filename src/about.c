/* Pitik: the About screen's version text. The stock V2.2 About window gets its version text from a small
 * getter at 0x1678C that only the About window uses (the Ampero Editor reads the version through a different
 * getter, which stays stock). The patch turns the getter's first instruction into a branch to about_version,
 * appended after the firmware's ITCM image, so About shows the identity "V2.2 + Pitik <version> <hash>".
 * tools/build_patch.py sets IDENT. Our code; MIT licence (LICENSE). */
#ifndef IDENT
#error "IDENT (the About identity string) comes from tools/build_patch.py"
#endif

const char *about_version(void)
{
    return IDENT;
}
