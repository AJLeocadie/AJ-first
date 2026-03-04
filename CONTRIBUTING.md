# Contribuer à NormaCheck

Merci de votre intérêt pour NormaCheck ! Voici comment contribuer.

## Processus de contribution

1. **Fork** le dépôt
2. **Créez** une branche (`git checkout -b feature/ma-fonctionnalite`)
3. **Commitez** vos changements (`git commit -m 'feat: ajouter ma fonctionnalité'`)
4. **Poussez** la branche (`git push origin feature/ma-fonctionnalite`)
5. **Ouvrez** une Pull Request

## Convention de commits

Nous utilisons [Conventional Commits](https://www.conventionalcommits.org/) :

- `feat:` nouvelle fonctionnalité
- `fix:` correction de bug
- `docs:` documentation
- `test:` ajout/modification de tests
- `refactor:` refactoring
- `chore:` maintenance

## Qualité du code

Avant de soumettre une PR, assurez-vous que :

```bash
# Les tests passent
python -m pytest tests/ -v

# Le linting est propre
ruff check .

# Le formatage est correct
ruff format --check .
```

## Signaler un bug

Ouvrez une [issue](https://github.com/AJLeocadie/AJ-first/issues) avec :

- Description du problème
- Étapes pour reproduire
- Comportement attendu vs obtenu
- Version de Python et OS

## Sécurité

Pour signaler une vulnérabilité, consultez [SECURITY.md](SECURITY.md).
