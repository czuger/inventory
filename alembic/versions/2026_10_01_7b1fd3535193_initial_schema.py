"""initial schema

Revision ID: 7b1fd3535193
Revises: 
Create Date: 2026-10-01 06:24:09.608434

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7b1fd3535193'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('associations',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('slug', sa.String(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_associations')),
    sa.UniqueConstraint('name', name=op.f('uq_associations_name')),
    sa.UniqueConstraint('slug', name=op.f('uq_associations_slug')),
    sqlite_autoincrement=True,
    sqlite_strict=True
    )
    op.create_table('games',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_games')),
    sa.UniqueConstraint('name', name=op.f('uq_games_name')),
    sqlite_autoincrement=True,
    sqlite_strict=True
    )
    op.create_table('legacy_object_ids',
    sa.Column('object_id', sa.String(), nullable=False),
    sa.Column('item_type', sa.String(), nullable=False),
    sa.Column('item_id', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('object_id', name=op.f('pk_legacy_object_ids')),
    sqlite_strict=True
    )
    op.create_table('users',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('discord_id', sa.String(), nullable=False),
    sa.Column('username', sa.String(), nullable=False),
    sa.Column('display_name', sa.String(), nullable=True),
    sa.Column('is_admin', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('discord_id', name=op.f('uq_users_discord_id')),
    sqlite_autoincrement=True,
    sqlite_strict=True
    )
    op.create_table('borrowings',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('association_id', sa.Integer(), nullable=False),
    sa.Column('borrower_id', sa.Integer(), nullable=False),
    sa.Column('item_id', sa.Integer(), nullable=False),
    sa.Column('item_type', sa.String(), nullable=False),
    sa.Column('action', sa.String(), nullable=False),
    sa.Column('date', sa.DateTime(), nullable=False),
    sa.CheckConstraint("action IN ('borrow', 'return')", name=op.f('ck_borrowings_action_choices')),
    sa.ForeignKeyConstraint(['association_id'], ['associations.id'], name=op.f('fk_borrowings_association_id_associations')),
    sa.ForeignKeyConstraint(['borrower_id'], ['users.id'], name=op.f('fk_borrowings_borrower_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_borrowings')),
    sqlite_autoincrement=True,
    sqlite_strict=True
    )
    with op.batch_alter_table('borrowings', schema=None) as batch_op:
        batch_op.create_index('ix_borrowings_item', ['item_type', 'item_id', 'date'], unique=False)

    op.create_table('duplicate_links',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('association_id', sa.Integer(), nullable=False),
    sa.Column('item1_id', sa.Integer(), nullable=False),
    sa.Column('item1_type', sa.String(), nullable=False),
    sa.Column('item2_id', sa.Integer(), nullable=False),
    sa.Column('item2_type', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['association_id'], ['associations.id'], name=op.f('fk_duplicate_links_association_id_associations')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_duplicate_links')),
    sqlite_autoincrement=True,
    sqlite_strict=True
    )
    with op.batch_alter_table('duplicate_links', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_duplicate_links_association_id'), ['association_id'], unique=False)

    op.create_table('locations',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('association_id', sa.Integer(), nullable=False),
    sa.Column('room', sa.String(), nullable=False),
    sa.Column('spot', sa.String(), nullable=False),
    sa.ForeignKeyConstraint(['association_id'], ['associations.id'], name=op.f('fk_locations_association_id_associations')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_locations')),
    sa.UniqueConstraint('association_id', 'room', 'spot', name=op.f('uq_locations_association_id_room_spot')),
    sqlite_autoincrement=True,
    sqlite_strict=True
    )
    op.create_table('board_games',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('association_id', sa.Integer(), nullable=False),
    sa.Column('category', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('universe', sa.String(), nullable=True),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('borrowing_count', sa.Integer(), nullable=False),
    sa.Column('sticker_printed', sa.Boolean(), nullable=False),
    sa.Column('location_id', sa.Integer(), nullable=False),
    sa.Column('images', sa.JSON(), nullable=False),
    sa.CheckConstraint("json_type(images) = 'array'", name=op.f('ck_board_games_images_is_array')),
    sa.ForeignKeyConstraint(['association_id'], ['associations.id'], name=op.f('fk_board_games_association_id_associations')),
    sa.ForeignKeyConstraint(['location_id'], ['locations.id'], name=op.f('fk_board_games_location_id_locations')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_board_games')),
    sqlite_autoincrement=True,
    sqlite_strict=True
    )
    with op.batch_alter_table('board_games', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_board_games_association_id'), ['association_id'], unique=False)

    op.create_table('books',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('association_id', sa.Integer(), nullable=False),
    sa.Column('category', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('universe', sa.String(), nullable=True),
    sa.Column('period', sa.String(), nullable=True),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('borrowing_count', sa.Integer(), nullable=False),
    sa.Column('sticker_printed', sa.Boolean(), nullable=False),
    sa.Column('location_id', sa.Integer(), nullable=False),
    sa.Column('images', sa.JSON(), nullable=False),
    sa.CheckConstraint("json_type(images) = 'array'", name=op.f('ck_books_images_is_array')),
    sa.ForeignKeyConstraint(['association_id'], ['associations.id'], name=op.f('fk_books_association_id_associations')),
    sa.ForeignKeyConstraint(['location_id'], ['locations.id'], name=op.f('fk_books_location_id_locations')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_books')),
    sqlite_autoincrement=True,
    sqlite_strict=True
    )
    with op.batch_alter_table('books', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_books_association_id'), ['association_id'], unique=False)

    op.create_table('consumables',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('association_id', sa.Integer(), nullable=False),
    sa.Column('category', sa.String(), nullable=False),
    sa.Column('type', sa.String(), nullable=False),
    sa.Column('unit', sa.String(), nullable=True),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('borrowing_count', sa.Integer(), nullable=False),
    sa.Column('sticker_printed', sa.Boolean(), nullable=False),
    sa.Column('location_id', sa.Integer(), nullable=False),
    sa.Column('images', sa.JSON(), nullable=False),
    sa.CheckConstraint("json_type(images) = 'array'", name=op.f('ck_consumables_images_is_array')),
    sa.ForeignKeyConstraint(['association_id'], ['associations.id'], name=op.f('fk_consumables_association_id_associations')),
    sa.ForeignKeyConstraint(['location_id'], ['locations.id'], name=op.f('fk_consumables_location_id_locations')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_consumables')),
    sqlite_autoincrement=True,
    sqlite_strict=True
    )
    with op.batch_alter_table('consumables', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_consumables_association_id'), ['association_id'], unique=False)

    op.create_table('equipment',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('association_id', sa.Integer(), nullable=False),
    sa.Column('category', sa.String(), nullable=False),
    sa.Column('type', sa.String(), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('borrowing_count', sa.Integer(), nullable=False),
    sa.Column('sticker_printed', sa.Boolean(), nullable=False),
    sa.Column('location_id', sa.Integer(), nullable=False),
    sa.Column('images', sa.JSON(), nullable=False),
    sa.CheckConstraint("json_type(images) = 'array'", name=op.f('ck_equipment_images_is_array')),
    sa.ForeignKeyConstraint(['association_id'], ['associations.id'], name=op.f('fk_equipment_association_id_associations')),
    sa.ForeignKeyConstraint(['location_id'], ['locations.id'], name=op.f('fk_equipment_location_id_locations')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_equipment')),
    sqlite_autoincrement=True,
    sqlite_strict=True
    )
    with op.batch_alter_table('equipment', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_equipment_association_id'), ['association_id'], unique=False)

    op.create_table('miniatures',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('association_id', sa.Integer(), nullable=False),
    sa.Column('category', sa.String(), nullable=False),
    sa.Column('type', sa.String(), nullable=False),
    sa.Column('game_id', sa.Integer(), nullable=False),
    sa.Column('scale', sa.String(), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('borrowing_count', sa.Integer(), nullable=False),
    sa.Column('sticker_printed', sa.Boolean(), nullable=False),
    sa.Column('location_id', sa.Integer(), nullable=False),
    sa.Column('images', sa.JSON(), nullable=False),
    sa.CheckConstraint("json_type(images) = 'array'", name=op.f('ck_miniatures_images_is_array')),
    sa.ForeignKeyConstraint(['association_id'], ['associations.id'], name=op.f('fk_miniatures_association_id_associations')),
    sa.ForeignKeyConstraint(['game_id'], ['games.id'], name=op.f('fk_miniatures_game_id_games')),
    sa.ForeignKeyConstraint(['location_id'], ['locations.id'], name=op.f('fk_miniatures_location_id_locations')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_miniatures')),
    sqlite_autoincrement=True,
    sqlite_strict=True
    )
    with op.batch_alter_table('miniatures', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_miniatures_association_id'), ['association_id'], unique=False)

    op.create_table('rulebooks',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('association_id', sa.Integer(), nullable=False),
    sa.Column('category', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('game_id', sa.Integer(), nullable=False),
    sa.Column('supplement', sa.Boolean(), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('borrowing_count', sa.Integer(), nullable=False),
    sa.Column('sticker_printed', sa.Boolean(), nullable=False),
    sa.Column('location_id', sa.Integer(), nullable=False),
    sa.Column('images', sa.JSON(), nullable=False),
    sa.CheckConstraint("json_type(images) = 'array'", name=op.f('ck_rulebooks_images_is_array')),
    sa.ForeignKeyConstraint(['association_id'], ['associations.id'], name=op.f('fk_rulebooks_association_id_associations')),
    sa.ForeignKeyConstraint(['game_id'], ['games.id'], name=op.f('fk_rulebooks_game_id_games')),
    sa.ForeignKeyConstraint(['location_id'], ['locations.id'], name=op.f('fk_rulebooks_location_id_locations')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rulebooks')),
    sqlite_autoincrement=True,
    sqlite_strict=True
    )
    with op.batch_alter_table('rulebooks', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_rulebooks_association_id'), ['association_id'], unique=False)

    op.create_table('tablecloths',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('association_id', sa.Integer(), nullable=False),
    sa.Column('category', sa.String(), nullable=False),
    sa.Column('type', sa.String(), nullable=False),
    sa.Column('material', sa.String(), nullable=True),
    sa.Column('game_id', sa.Integer(), nullable=False),
    sa.Column('size', sa.String(), nullable=False),
    sa.Column('remarks', sa.String(), nullable=True),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('borrowing_count', sa.Integer(), nullable=False),
    sa.Column('sticker_printed', sa.Boolean(), nullable=False),
    sa.Column('location_id', sa.Integer(), nullable=False),
    sa.Column('images', sa.JSON(), nullable=False),
    sa.CheckConstraint("json_type(images) = 'array'", name=op.f('ck_tablecloths_images_is_array')),
    sa.CheckConstraint("material IN ('mousepad (neoprene)', 'vinyl', 'cloth', 'textured')", name=op.f('ck_tablecloths_material_choices')),
    sa.ForeignKeyConstraint(['association_id'], ['associations.id'], name=op.f('fk_tablecloths_association_id_associations')),
    sa.ForeignKeyConstraint(['game_id'], ['games.id'], name=op.f('fk_tablecloths_game_id_games')),
    sa.ForeignKeyConstraint(['location_id'], ['locations.id'], name=op.f('fk_tablecloths_location_id_locations')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tablecloths')),
    sqlite_autoincrement=True,
    sqlite_strict=True
    )
    with op.batch_alter_table('tablecloths', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_tablecloths_association_id'), ['association_id'], unique=False)

    op.create_table('terrains',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('association_id', sa.Integer(), nullable=False),
    sa.Column('category', sa.String(), nullable=False),
    sa.Column('type', sa.String(), nullable=False),
    sa.Column('game_id', sa.Integer(), nullable=False),
    sa.Column('scale', sa.String(), nullable=False),
    sa.Column('theater', sa.String(), nullable=True),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('borrowing_count', sa.Integer(), nullable=False),
    sa.Column('sticker_printed', sa.Boolean(), nullable=False),
    sa.Column('location_id', sa.Integer(), nullable=False),
    sa.Column('images', sa.JSON(), nullable=False),
    sa.CheckConstraint("json_type(images) = 'array'", name=op.f('ck_terrains_images_is_array')),
    sa.ForeignKeyConstraint(['association_id'], ['associations.id'], name=op.f('fk_terrains_association_id_associations')),
    sa.ForeignKeyConstraint(['game_id'], ['games.id'], name=op.f('fk_terrains_game_id_games')),
    sa.ForeignKeyConstraint(['location_id'], ['locations.id'], name=op.f('fk_terrains_location_id_locations')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_terrains')),
    sqlite_autoincrement=True,
    sqlite_strict=True
    )
    with op.batch_alter_table('terrains', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_terrains_association_id'), ['association_id'], unique=False)



def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('terrains', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_terrains_association_id'))

    op.drop_table('terrains')
    with op.batch_alter_table('tablecloths', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_tablecloths_association_id'))

    op.drop_table('tablecloths')
    with op.batch_alter_table('rulebooks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_rulebooks_association_id'))

    op.drop_table('rulebooks')
    with op.batch_alter_table('miniatures', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_miniatures_association_id'))

    op.drop_table('miniatures')
    with op.batch_alter_table('equipment', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_equipment_association_id'))

    op.drop_table('equipment')
    with op.batch_alter_table('consumables', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_consumables_association_id'))

    op.drop_table('consumables')
    with op.batch_alter_table('books', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_books_association_id'))

    op.drop_table('books')
    with op.batch_alter_table('board_games', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_board_games_association_id'))

    op.drop_table('board_games')
    op.drop_table('locations')
    with op.batch_alter_table('duplicate_links', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_duplicate_links_association_id'))

    op.drop_table('duplicate_links')
    with op.batch_alter_table('borrowings', schema=None) as batch_op:
        batch_op.drop_index('ix_borrowings_item')

    op.drop_table('borrowings')
    op.drop_table('users')
    op.drop_table('legacy_object_ids')
    op.drop_table('games')
    op.drop_table('associations')
