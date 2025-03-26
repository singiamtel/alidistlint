# alidistlint.nvim

Neovim LSP integration for alidistlint.

## Requirements

- Neovim >= 0.8.0
- alidistlint installed and available in your PATH
- nvim-lspconfig

## Installation

Using your preferred plugin manager:

### packer
```lua
use {
  'your-username/alidistlint.nvim',
  requires = {
    'neovim/nvim-lspconfig',
  },
}
```

### lazy.nvim
```lua
{
  'your-username/alidistlint.nvim',
  dependencies = {
    'neovim/nvim-lspconfig',
  },
}
```

## Configuration

Add this to your Neovim configuration:

```lua
require('alidistlint').setup({
  -- Optional configuration
  cmd = { 'alidistlint' }, -- Command to run
  filetypes = { 'yaml' },  -- File types to enable the linter for
  settings = {
    -- Add any settings here if needed
  },
})
```

## Features

- LSP integration for alidistlint
- Automatic diagnostics in YAML files
- Works with alidist package files
- Real-time error reporting

## License

Same as the main alidistlint project (GPLv3) 